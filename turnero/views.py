"""
views.py — Vistas del módulo turnero.
Gestiona autenticación, registro, inicio y el flujo completo de consultas médicas.
"""

from datetime import datetime as dt

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Max
from django.views.decorators.http import require_GET, require_POST

from .decorators import admin_requerido
from .forms import (
    SolicitudConsultaForm,
    SedeForm,
    ServicioForm,
    SedeServicioForm,
)
from .models import Sede, SedeServicio, Servicio, Turno, Usuario


# =============================================================================
# Vistas de autenticación
# =============================================================================

def inicio(request):
    """Vista de inicio de sesión."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        tipo_doc = request.POST.get('tipo_doc')
        num_doc = request.POST.get('num_doc')
        password = request.POST.get('password')

        try:
            usuario = Usuario.objects.get(tipo_documento=tipo_doc, num_documento=num_doc)

            if usuario.check_password(password):
                usuario.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, usuario)
                return redirect('home')
            else:
                messages.error(request, 'Contraseña incorrecta.')
        except Usuario.DoesNotExist:
            messages.error(request, 'No existe un usuario con este documento.')

    return render(request, 'Login.html')


def registro(request):
    """Vista de registro de nuevos usuarios."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        nombre = request.POST.get('nombre_completo')
        tipo_doc = request.POST.get('tipo_doc')
        num_doc = request.POST.get('identificacion')
        email = request.POST.get('correo')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')

        if password != password_confirm:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(request, 'Register.html')

        if Usuario.objects.filter(num_documento=num_doc).exists():
            messages.error(request, 'Ya existe una cuenta con este número de documento.')
            return render(request, 'Register.html')

        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Este correo electrónico ya está registrado.')
            return render(request, 'Register.html')

        # Crear el usuario nuevo con rol de paciente
        usuario = Usuario.objects.create_user(
            email=email,
            num_documento=num_doc,
            nombre=nombre,
            password=password,
            tipo_documento=tipo_doc
        )

        # Asignar al grupo Paciente si existe
        try:
            grupo = Group.objects.get(name='Paciente')
            usuario.groups.add(grupo)
        except Group.DoesNotExist:
            pass

        usuario.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, usuario)
        return redirect('home')

    return render(request, 'Register.html')


def home(request):
    """Vista principal del dashboard del paciente."""
    if not request.user.is_authenticated:
        return redirect('inicio')

    servicios = [
        {"nombre": "Laboratorio", "tiempo_estimado": "Pendiente"},
        {"nombre": "Pagos", "tiempo_estimado": "Pendiente"},
        {"nombre": "Consultas Médicas", "tiempo_estimado": "Pendiente", "url": "consultas"},
        {"nombre": "Atención al cliente", "tiempo_estimado": "Pendiente"},
        {"nombre": "Farmacia", "tiempo_estimado": "Pendiente"},
        {"nombre": "Vacunación", "tiempo_estimado": "Pendiente"},
    ]

    # Determinar si el usuario tiene privilegios de administrador
    usuario = request.user
    es_admin = (
        usuario.is_superuser
        or (usuario.is_staff and usuario.groups.filter(name='Administrador').exists())
    )

    contexto = {
        "nombre_usuario": request.user.nombre,
        "servicios": servicios,
        "es_admin": es_admin,
    }

    return render(request, 'home.html', contexto)


def salir(request):
    """Cierra la sesión del usuario y redirige al inicio."""
    logout(request)
    return redirect('inicio')


# =============================================================================
# Vistas del módulo de Consultas Médicas
# =============================================================================

@login_required(login_url='inicio')
def consultas(request):
    """
    Página de aterrizaje del módulo de Consultas Médicas.
    Muestra el submenú con las cuatro acciones disponibles.
    """
    return render(request, 'consultas.html')


@login_required(login_url='inicio')
def solicitar_consulta(request):
    """
    Vista para solicitar una nueva consulta médica.

    GET  → muestra el formulario vacío.
    POST → valida los datos, crea el Turno en BD y redirige
           a la página de confirmación.
    """
    if request.method == 'POST':
        formulario = SolicitudConsultaForm(request.POST, usuario=request.user)

        if formulario.is_valid():
            # Extraer datos validados del formulario
            sede = formulario.cleaned_data['sede']
            servicio = formulario.cleaned_data['servicio']
            fecha = formulario.cleaned_data['fecha_turno']
            hora_str = formulario.cleaned_data['hora_consulta']

            # Convertir la franja horaria a objeto time para guardar en BD
            hora_obj = dt.strptime(hora_str, '%H:%M').time()

            # Buscar la relación SedeServicio correspondiente
            try:
                sede_servicio = SedeServicio.objects.get(sede=sede, servicio=servicio)
            except SedeServicio.DoesNotExist:
                messages.error(
                    request,
                    'El servicio seleccionado no está disponible en esa sede. '
                    'Por favor elige otra combinación.'
                )
                return render(request, 'solicitud_cita.html', {'formulario': formulario})

            # Calcular el consecutivo diario para esta SedeServicio y fecha
            max_consecutivo = Turno.objects.filter(
                sede_servicio=sede_servicio,
                fecha_turno=fecha
            ).aggregate(Max('consecutivo_diario'))['consecutivo_diario__max']

            # Si no hay turnos aún para ese día, empezar en 1
            consecutivo = (max_consecutivo or 0) + 1

            # Generar código visual: prefijo + consecutivo de 3 dígitos
            codigo = f"{sede_servicio.prefijo}{consecutivo:03d}"

            # Crear y guardar el Turno en la base de datos
            turno = Turno.objects.create(
                sede_servicio=sede_servicio,
                fecha_turno=fecha,
                hora_cita=hora_obj,
                consecutivo_diario=consecutivo,
                codigo_visual=codigo,
                estado='en_espera',
                usuario=request.user,
            )

            # Guardar datos en sesión para la página de confirmación
            request.session['consulta_exitosa'] = {
                'codigo_visual': turno.codigo_visual,
                'sede': sede.nombre,
                'servicio': servicio.nombre,
                'fecha': str(fecha),
                'hora': hora_str,
                'consecutivo': consecutivo,
            }

            return redirect('consulta_exitosa')

    else:
        # Solicitud GET — mostrar formulario vacío
        formulario = SolicitudConsultaForm(usuario=request.user)

    return render(request, 'solicitud_cita.html', {'formulario': formulario})


@login_required(login_url='inicio')
def consulta_exitosa(request):
    """
    Página de confirmación tras solicitar una consulta exitosamente.
    Recupera los datos del turno desde la sesión y los muestra al paciente.
    """
    # Recuperar y eliminar los datos de sesión (evita re-mostrar al recargar)
    datos_consulta = request.session.pop('consulta_exitosa', None)

    if not datos_consulta:
        # Sin datos en sesión → redirigir al formulario
        return redirect('solicitar_consulta')

    return render(request, 'cita_exitosa.html', {'cita': datos_consulta})


@login_required(login_url='inicio')
def mis_consultas(request):
    """
    Lista las consultas médicas activas (estado 'en_espera') del usuario autenticado.
    Ordena por fecha de turno ascendente.
    """
    consultas_activas = (
        Turno.objects
        .filter(usuario=request.user, estado='en_espera')
        .select_related('sede_servicio__sede', 'sede_servicio__servicio')
        .order_by('fecha_turno')
    )

    return render(request, 'mis_consultas.html', {'consultas': consultas_activas})


@login_required(login_url='inicio')
def cancelar_consulta(request):
    """
    Vista para cancelar una consulta médica.

    GET  → muestra los turnos activos del usuario con botón cancelar.
    POST → recibe turno_id, verifica propiedad, cambia estado a 'cancelado'.
    """
    if request.method == 'POST':
        turno_id = request.POST.get('turno_id')
        turno = get_object_or_404(Turno, pk=turno_id)

        # Verificar que el turno pertenece al usuario autenticado
        if turno.usuario != request.user:
            messages.error(request, 'No tienes permiso para cancelar esta consulta.')
            return redirect('cancelar_consulta')

        # Verificar que el turno aún está en espera
        if turno.estado != 'en_espera':
            messages.error(request, 'Esta consulta ya no puede ser cancelada.')
            return redirect('cancelar_consulta')

        # Cambiar estado a cancelado (no se elimina el registro)
        turno.estado = 'cancelado'
        turno.save(update_fields=['estado'])

        messages.success(
            request,
            f'La consulta {turno.codigo_visual} ha sido cancelada exitosamente.'
        )
        return redirect('mis_consultas')

    # GET — listar turnos activos del usuario
    consultas_activas = (
        Turno.objects
        .filter(usuario=request.user, estado='en_espera')
        .select_related('sede_servicio__sede', 'sede_servicio__servicio')
        .order_by('fecha_turno', 'hora_cita')
    )
    return render(request, 'cancelar_consulta.html', {'consultas': consultas_activas})


@login_required(login_url='inicio')
def reprogramar_consulta(request):
    """
    Vista de selección: lista los turnos activos del usuario
    para que elija cuál reprogramar.
    """
    consultas_activas = (
        Turno.objects
        .filter(usuario=request.user, estado='en_espera')
        .select_related('sede_servicio__sede', 'sede_servicio__servicio')
        .order_by('fecha_turno', 'hora_cita')
    )
    return render(request, 'reprogramar_consulta.html', {'consultas': consultas_activas})


@login_required(login_url='inicio')
def reprogramar_consulta_detalle(request, turno_id):
    """
    Formulario de reprogramación para un turno específico.

    GET  → muestra formulario con nueva fecha y hora.
    POST → valida disponibilidad, actualiza fecha_turno y hora_cita.
    """
    turno = get_object_or_404(Turno, pk=turno_id)

    # Verificar propiedad y estado
    if turno.usuario != request.user:
        messages.error(request, 'No tienes permiso para reprogramar esta consulta.')
        return redirect('reprogramar_consulta')

    if turno.estado != 'en_espera':
        messages.error(request, 'Esta consulta ya no puede ser reprogramada.')
        return redirect('reprogramar_consulta')

    from .forms import FRANJAS_HORARIAS

    if request.method == 'POST':
        nueva_fecha_str = request.POST.get('fecha_turno')
        nueva_hora_str = request.POST.get('hora_consulta')
        errores = []

        # Validar fecha
        from django.utils import timezone
        try:
            nueva_fecha = dt.strptime(nueva_fecha_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            errores.append('Fecha inválida.')
            nueva_fecha = None

        if nueva_fecha and nueva_fecha < timezone.localdate():
            errores.append('La fecha no puede ser en el pasado.')

        # Validar hora
        horas_validas = {h for h, _ in FRANJAS_HORARIAS}
        if not nueva_hora_str or nueva_hora_str not in horas_validas:
            errores.append('Debe seleccionar una franja horaria válida.')

        nueva_hora_obj = None
        if nueva_hora_str and nueva_hora_str in horas_validas:
            nueva_hora_obj = dt.strptime(nueva_hora_str, '%H:%M').time()

        # Validar franja pasada si es hoy
        if nueva_fecha and nueva_hora_obj and nueva_fecha == timezone.localdate():
            if nueva_hora_obj <= timezone.localtime().time():
                errores.append('La franja seleccionada ya pasó para hoy.')

        # Validar disponibilidad del slot
        if nueva_fecha and nueva_hora_obj and not errores:
            conflicto = Turno.objects.filter(
                sede_servicio=turno.sede_servicio,
                fecha_turno=nueva_fecha,
                hora_cita=nueva_hora_obj,
                estado='en_espera',
            ).exclude(pk=turno.pk).exists()
            if conflicto:
                errores.append('La franja seleccionada ya está ocupada.')

            # Doble reserva del mismo usuario
            conflicto_usuario = Turno.objects.filter(
                usuario=request.user,
                fecha_turno=nueva_fecha,
                hora_cita=nueva_hora_obj,
                estado='en_espera',
            ).exclude(pk=turno.pk).exists()
            if conflicto_usuario:
                errores.append('Ya tienes otra consulta en esa fecha y hora.')

        if errores:
            for err in errores:
                messages.error(request, err)
            contexto = {
                'turno': turno,
                'franjas': FRANJAS_HORARIAS,
                'fecha_valor': nueva_fecha_str or '',
                'hora_valor': nueva_hora_str or '',
            }
            return render(request, 'reprogramar_consulta_detalle.html', contexto)

        # Guardar los cambios
        turno.fecha_turno = nueva_fecha
        turno.hora_cita = nueva_hora_obj
        turno.save(update_fields=['fecha_turno', 'hora_cita'])

        messages.success(
            request,
            f'La consulta {turno.codigo_visual} fue reprogramada al '
            f'{nueva_fecha_str} a las {nueva_hora_str}.'
        )
        return redirect('mis_consultas')

    # GET
    contexto = {
        'turno': turno,
        'franjas': FRANJAS_HORARIAS,
        'fecha_valor': '',
        'hora_valor': '',
    }
    return render(request, 'reprogramar_consulta_detalle.html', contexto)


# =============================================================================
# API — Franjas horarias disponibles (AJAX)
# =============================================================================

@login_required(login_url='inicio')
@require_GET
def api_franjas_disponibles(request):
    """
    Endpoint JSON que retorna las franjas horarias libres para una
    combinación de sede + servicio + fecha.

    Parámetros GET:
        sede      — cod_sede
        servicio  — cod_servicio
        fecha     — YYYY-MM-DD
    """
    cod_sede = request.GET.get('sede', '')
    cod_servicio = request.GET.get('servicio', '')
    fecha_str = request.GET.get('fecha', '')

    # Validar parámetros requeridos
    if not (cod_sede and cod_servicio and fecha_str):
        return JsonResponse({'error': 'Parámetros incompletos.'}, status=400)

    # Parsear la fecha
    try:
        fecha = dt.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido.'}, status=400)

    # Buscar la relación SedeServicio
    try:
        sede_servicio = SedeServicio.objects.get(
            sede_id=cod_sede, servicio_id=cod_servicio
        )
    except SedeServicio.DoesNotExist:
        return JsonResponse({'error': 'Combinación sede-servicio no encontrada.'}, status=404)

    # Obtener las horas ya reservadas (solo turnos activos)
    # Parámetro opcional: excluir un turno específico (para reprogramación)
    excluir = request.GET.get('excluir', '')
    qs_turnos = Turno.objects.filter(
        sede_servicio=sede_servicio,
        fecha_turno=fecha,
        estado='en_espera',
    )
    if excluir:
        qs_turnos = qs_turnos.exclude(pk=excluir)

    horas_ocupadas = set(qs_turnos.values_list('hora_cita', flat=True))

    # Generar franjas libres
    from .forms import FRANJAS_HORARIAS
    franjas_libres = []
    for valor, etiqueta in FRANJAS_HORARIAS:
        hora_obj = dt.strptime(valor, '%H:%M').time()
        if hora_obj not in horas_ocupadas:
            franjas_libres.append({'valor': valor, 'etiqueta': etiqueta})

    return JsonResponse({'franjas': franjas_libres})


# =============================================================================
# Vistas del Panel de Administración (RBAC)
# =============================================================================

@admin_requerido
def panel_admin(request):
    """
    Dashboard del panel de administración.
    Muestra tarjetas con las acciones de gestión disponibles.
    """
    # Contadores para el resumen del dashboard
    contexto = {
        'total_sedes': Sede.objects.count(),
        'total_servicios': Servicio.objects.count(),
        'total_vinculaciones': SedeServicio.objects.count(),
    }
    return render(request, 'panel_admin.html', contexto)


# ---- Gestión de Sedes -------------------------------------------------------

@admin_requerido
def crear_sede(request):
    """Formulario para registrar una nueva sede."""
    if request.method == 'POST':
        formulario = SedeForm(request.POST)
        if formulario.is_valid():
            formulario.save()
            messages.success(
                request,
                f'La sede "{formulario.cleaned_data["nombre"]}" fue creada exitosamente.'
            )
            return redirect('listar_sedes')
    else:
        formulario = SedeForm()

    return render(request, 'crear_sede.html', {'formulario': formulario})


@admin_requerido
def listar_sedes(request):
    """Lista todas las sedes registradas en el sistema."""
    sedes = Sede.objects.all().order_by('nombre')
    return render(request, 'listar_sedes.html', {'sedes': sedes})


# ---- Gestión de Servicios ----------------------------------------------------

@admin_requerido
def crear_servicio(request):
    """Formulario para registrar un nuevo servicio."""
    if request.method == 'POST':
        formulario = ServicioForm(request.POST)
        if formulario.is_valid():
            formulario.save()
            messages.success(
                request,
                f'El servicio "{formulario.cleaned_data["nombre"]}" fue creado exitosamente.'
            )
            return redirect('listar_servicios')
    else:
        formulario = ServicioForm()

    return render(request, 'crear_servicio.html', {'formulario': formulario})


@admin_requerido
def listar_servicios(request):
    """Lista todos los servicios registrados en el sistema."""
    servicios = Servicio.objects.all().order_by('nombre')
    return render(request, 'listar_servicios.html', {'servicios': servicios})


# ---- Gestión de Vinculación Sede-Servicio ------------------------------------

@admin_requerido
def crear_sede_servicio(request):
    """Formulario para vincular una sede con un servicio (incluye prefijo)."""
    if request.method == 'POST':
        formulario = SedeServicioForm(request.POST)
        if formulario.is_valid():
            formulario.save()
            sede = formulario.cleaned_data['sede']
            servicio = formulario.cleaned_data['servicio']
            messages.success(
                request,
                f'Vinculación "{sede} — {servicio}" creada exitosamente.'
            )
            return redirect('listar_sede_servicios')
    else:
        formulario = SedeServicioForm()

    return render(request, 'crear_sede_servicio.html', {'formulario': formulario})


@admin_requerido
def listar_sede_servicios(request):
    """Lista todas las vinculaciones sede-servicio con su prefijo."""
    vinculaciones = (
        SedeServicio.objects
        .select_related('sede', 'servicio')
        .order_by('sede__nombre', 'servicio__nombre')
    )
    return render(request, 'listar_sede_servicios.html', {'vinculaciones': vinculaciones})