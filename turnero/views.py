"""
views.py — Vistas del módulo turnero.
Gestiona autenticación, registro, inicio y el flujo completo de consultas médicas.
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Max

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
        formulario = SolicitudConsultaForm(request.POST)

        if formulario.is_valid():
            # Extraer datos validados del formulario
            sede = formulario.cleaned_data['sede']
            servicio = formulario.cleaned_data['servicio']
            fecha = formulario.cleaned_data['fecha_turno']
            hora = formulario.cleaned_data['hora_consulta']

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
            # Ejemplo: prefijo='LAB' → 'LAB001'
            codigo = f"{sede_servicio.prefijo}{consecutivo:03d}"

            # Crear y guardar el Turno en la base de datos
            turno = Turno.objects.create(
                sede_servicio=sede_servicio,
                fecha_turno=fecha,
                consecutivo_diario=consecutivo,
                codigo_visual=codigo,
                estado='en_espera',
                usuario=request.user,   # Vincular al paciente autenticado
            )

            # Guardar datos en sesión para la página de confirmación
            request.session['consulta_exitosa'] = {
                'codigo_visual': turno.codigo_visual,
                'sede': sede.nombre,
                'servicio': servicio.nombre,
                'fecha': str(fecha),
                'hora': str(hora),
                'consecutivo': consecutivo,
            }

            return redirect('consulta_exitosa')

    else:
        # Solicitud GET — mostrar formulario vacío
        formulario = SolicitudConsultaForm()

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
    """Vista para cancelar una consulta médica (función en desarrollo)."""
    return render(request, 'cancelar_consulta.html')


@login_required(login_url='inicio')
def reprogramar_consulta(request):
    """Vista para reprogramar una consulta médica (función en desarrollo)."""
    return render(request, 'reprogramar_consulta.html')


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