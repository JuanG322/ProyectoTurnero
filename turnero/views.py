"""
views.py — Vistas del módulo turnero.
Gestiona autenticación, registro, inicio y el flujo completo de consultas médicas.
"""

import io
import json
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime as dt, timedelta

import qrcode
from openai import OpenAI as DeepSeekClient
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Count, Max, Q
from django.views.decorators.http import require_GET, require_POST

from .decorators import admin_requerido, operador_requerido
from .forms import (
    SolicitudConsultaForm,
    SedeForm,
    SedeFarmaciaForm,
    ServicioForm,
    SedeServicioForm,
    PQRSForm,
)
from .models import (
    PQRS, Sede, SedeServicio, SedeFarmacia, Servicio,
    TokenQRFarmacia, Turno, Usuario,
)


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
    """Vista principal del dashboard."""
    if not request.user.is_authenticated:
        return redirect('inicio')

    servicios = [
        {"nombre": "Consultas Médicas", "tiempo_estimado": "Disponible", "url": "consultas"},
        {"nombre": "Procedimientos Clínicos", "tiempo_estimado": "Disponible", "url": "procedimientos"},
        {"nombre": "Farmacia", "tiempo_estimado": "Disponible", "url": "farmacia_info"},
        {"nombre": "Atención al cliente", "tiempo_estimado": "Disponible", "url": "atencion_cliente"},
    ]

    usuario = request.user
    es_admin = (
        usuario.is_superuser
        or (usuario.is_staff and usuario.groups.filter(name='Administrador').exists())
    )
    es_operador = (
        usuario.is_superuser
        or (usuario.is_staff and usuario.groups.filter(name='Operador').exists())
    )

    contexto = {
        "nombre_usuario": request.user.nombre,
        "servicios": servicios,
        "es_admin": es_admin,
        "es_operador": es_operador,
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


# =============================================================================
# Vistas del módulo de Procedimientos Clínicos (Laboratorio + Vacunación)
# =============================================================================

@login_required(login_url='inicio')
def procedimientos(request):
    """
    Página de aterrizaje del módulo de Procedimientos Clínicos.
    Muestra las opciones: Laboratorio y Vacunación, ambos con flujo
    de cita programada que reutiliza el modelo Turno.
    """
    return render(request, 'procedimientos.html')


@login_required(login_url='inicio')
def solicitar_consulta(request):
    """
    Vista para solicitar una nueva consulta médica o procedimiento clínico.

    Acepta ?categoria=medicina|procedimientos para filtrar servicios.
    GET  → muestra el formulario vacío.
    POST → valida los datos, crea el Turno en BD y redirige
           a la página de confirmación.
    """
    categoria = request.GET.get('categoria', request.POST.get('categoria', 'medicina'))

    # Contexto dinámico según la categoría
    if categoria == 'procedimientos':
        titulo = 'Solicitar procedimiento clínico'
        subtitulo = 'Completa el formulario para agendar tu cita de laboratorio o vacunación.'
        back_url = 'procedimientos'
        back_label = 'Volver a Procedimientos Clínicos'
    else:
        titulo = 'Solicitar consulta médica'
        subtitulo = 'Completa el formulario para reservar tu lugar. El turno quedará asignado automáticamente.'
        back_url = 'consultas'
        back_label = 'Volver a Consultas Médicas'

    if request.method == 'POST':
        formulario = SolicitudConsultaForm(
            request.POST, usuario=request.user, categoria=categoria
        )

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
                return render(request, 'solicitud_cita.html', {
                    'formulario': formulario, 'titulo': titulo,
                    'subtitulo': subtitulo, 'back_url': back_url,
                    'back_label': back_label, 'categoria': categoria,
                })

            # Calcular el consecutivo diario para esta SedeServicio y fecha
            max_consecutivo = Turno.objects.filter(
                sede_servicio=sede_servicio,
                fecha_turno=fecha
            ).aggregate(Max('consecutivo_diario'))['consecutivo_diario__max']

            # Si no hay turnos aún para ese día, empezar en 1
            consecutivo = (max_consecutivo or 0) + 1

            # Generar código visual: prefijo + consecutivo de 3 dígitos
            codigo = f"{sede_servicio.prefijo}{consecutivo:03d}"

            # Determinar tipo_servicio a partir de la categoría del servicio
            tipo_map = {
                'MEDICINA': 'MEDICINA',
                'LABORATORIO': 'LABORATORIO',
                'VACUNACION': 'VACUNACION',
            }
            tipo_servicio = tipo_map.get(servicio.categoria, 'MEDICINA')

            # Crear y guardar el Turno en la base de datos
            turno = Turno.objects.create(
                tipo_servicio=tipo_servicio,
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
        formulario = SolicitudConsultaForm(usuario=request.user, categoria=categoria)

    return render(request, 'solicitud_cita.html', {
        'formulario': formulario, 'titulo': titulo,
        'subtitulo': subtitulo, 'back_url': back_url,
        'back_label': back_label, 'categoria': categoria,
    })


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
        'total_sedes_farmacia': SedeFarmacia.objects.count(),
        'total_pqrs': PQRS.objects.count(),
        'pqrs_pendientes': PQRS.objects.exclude(estado='resuelto').count(),
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
            servicio = formulario.save()
            messages.success(
                request,
                f'Servicio de {servicio.get_categoria_display()} '
                f'"{servicio.nombre}" creado exitosamente.'
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


# ---- Editar / Eliminar Sedes ------------------------------------------------

@admin_requerido
def editar_sede(request, pk):
    sede = get_object_or_404(Sede, pk=pk)
    if request.method == 'POST':
        formulario = SedeForm(request.POST, instance=sede)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, f'La sede "{sede.nombre}" fue actualizada.')
            return redirect('listar_sedes')
    else:
        formulario = SedeForm(instance=sede)
    return render(request, 'editar_sede.html', {'formulario': formulario, 'sede': sede})


@admin_requerido
@require_POST
def eliminar_sede(request, pk):
    sede = get_object_or_404(Sede, pk=pk)
    turnos_activos = Turno.objects.filter(
        sede_servicio__sede=sede, estado='en_espera'
    ).count()
    if turnos_activos > 0:
        messages.error(
            request,
            f'No se puede eliminar la sede "{sede.nombre}" porque tiene '
            f'{turnos_activos} turno(s) pendiente(s).'
        )
        return redirect('listar_sedes')
    sede.delete()
    messages.success(request, f'La sede "{sede.nombre}" fue eliminada.')
    return redirect('listar_sedes')


# ---- Editar / Eliminar Servicios --------------------------------------------

@admin_requerido
def editar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk)
    if request.method == 'POST':
        formulario = ServicioForm(request.POST, instance=servicio)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, f'El servicio "{servicio.nombre}" fue actualizado.')
            return redirect('listar_servicios')
    else:
        formulario = ServicioForm(instance=servicio)
    return render(request, 'editar_servicio.html', {'formulario': formulario, 'servicio': servicio})


@admin_requerido
@require_POST
def eliminar_servicio(request, pk):
    servicio = get_object_or_404(Servicio, pk=pk)
    turnos_activos = Turno.objects.filter(
        sede_servicio__servicio=servicio, estado='en_espera'
    ).count()
    if turnos_activos > 0:
        messages.error(
            request,
            f'No se puede eliminar el servicio "{servicio.nombre}" porque tiene '
            f'{turnos_activos} turno(s) pendiente(s).'
        )
        return redirect('listar_servicios')
    servicio.delete()
    messages.success(request, f'El servicio "{servicio.nombre}" fue eliminado.')
    return redirect('listar_servicios')


# ---- Editar / Eliminar Vinculaciones Sede-Servicio --------------------------

@admin_requerido
def editar_sede_servicio(request, pk):
    vinculacion = get_object_or_404(SedeServicio, pk=pk)
    if request.method == 'POST':
        formulario = SedeServicioForm(request.POST, instance=vinculacion)
        if formulario.is_valid():
            formulario.save()
            messages.success(request, 'La vinculación fue actualizada.')
            return redirect('listar_sede_servicios')
    else:
        formulario = SedeServicioForm(instance=vinculacion)
    return render(request, 'editar_sede_servicio.html', {
        'formulario': formulario, 'vinculacion': vinculacion,
    })


@admin_requerido
@require_POST
def eliminar_sede_servicio(request, pk):
    vinculacion = get_object_or_404(SedeServicio, pk=pk)
    turnos_activos = Turno.objects.filter(
        sede_servicio=vinculacion, estado='en_espera'
    ).count()
    if turnos_activos > 0:
        messages.error(
            request,
            f'No se puede eliminar la vinculación "{vinculacion.sede} — {vinculacion.servicio}" '
            f'porque tiene {turnos_activos} turno(s) pendiente(s).'
        )
        return redirect('listar_sede_servicios')
    vinculacion.delete()
    messages.success(
        request,
        f'La vinculación "{vinculacion.sede} — {vinculacion.servicio}" fue eliminada.'
    )
    return redirect('listar_sede_servicios')


# =============================================================================
# ---- Gestión de Sedes de Farmacia -------------------------------------------

@admin_requerido
def crear_sede_farmacia(request):
    """Formulario para registrar una nueva sede de farmacia."""
    if request.method == 'POST':
        formulario = SedeFarmaciaForm(request.POST)
        if formulario.is_valid():
            formulario.save()
            messages.success(
                request,
                f'La sede de farmacia "{formulario.cleaned_data["nombre"]}" '
                f'fue registrada exitosamente.'
            )
            return redirect('panel_admin')
    else:
        formulario = SedeFarmaciaForm()
    return render(request, 'crear_sede_farmacia.html', {'formulario': formulario})


@admin_requerido
def listar_sedes_farmacia(request):
    """Lista todas las sedes de farmacia registradas."""
    sedes = SedeFarmacia.objects.all().order_by('ciudad', 'nombre')
    return render(request, 'listar_sedes_farmacia.html', {'sedes': sedes})


@admin_requerido
def editar_sede_farmacia(request, pk):
    """Formulario para editar una sede de farmacia existente."""
    sede = get_object_or_404(SedeFarmacia, pk=pk)
    if request.method == 'POST':
        formulario = SedeFarmaciaForm(request.POST, instance=sede)
        if formulario.is_valid():
            formulario.save()
            messages.success(
                request, f'La sede de farmacia "{sede.nombre}" fue actualizada.'
            )
            return redirect('listar_sedes_farmacia')
    else:
        formulario = SedeFarmaciaForm(instance=sede)
    return render(request, 'editar_sede_farmacia.html', {
        'formulario': formulario, 'sede': sede,
    })


@admin_requerido
@require_POST
def eliminar_sede_farmacia(request, pk):
    """Elimina una sede de farmacia si no tiene turnos pendientes."""
    sede = get_object_or_404(SedeFarmacia, pk=pk)
    turnos_activos = Turno.objects.filter(
        sede_farmacia=sede, estado='en_espera'
    ).count()
    if turnos_activos > 0:
        messages.error(
            request,
            f'No se puede eliminar la sede "{sede.nombre}" porque tiene '
            f'{turnos_activos} turno(s) pendiente(s).',
        )
        return redirect('listar_sedes_farmacia')
    sede.delete()
    messages.success(request, f'La sede de farmacia "{sede.nombre}" fue eliminada.')
    return redirect('listar_sedes_farmacia')

# =============================================================================
# Vistas del Panel de Operador
# =============================================================================

ESTADOS_VALIDOS = {
    'llamando': 'llamando',
    'en_atencion': 'en_atencion',
    'atendido': 'atendido',
    'no_asistio': 'no_asistio',
}


@operador_requerido
def panel_operador(request):
    """
    Dashboard del operador: muestra la cola de turnos para una fecha dada.
    Permite filtrar por fecha, sede, servicio y estado.
    """
    from django.utils import timezone
    hoy = timezone.localdate()

    # Fecha seleccionada (por defecto: hoy)
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            fecha_seleccionada = dt.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_seleccionada = hoy
    else:
        fecha_seleccionada = hoy

    es_hoy = (fecha_seleccionada == hoy)

    # Filtros opcionales
    filtro_sede = request.GET.get('sede', '')
    filtro_servicio = request.GET.get('servicio', '')
    filtro_estado = request.GET.get('estado', '')

    qs = (
        Turno.objects
        .filter(fecha_turno=fecha_seleccionada)
        .select_related(
            'sede_servicio__sede',
            'sede_servicio__servicio',
            'usuario',
        )
        .order_by('hora_cita', 'consecutivo_diario')
    )

    if filtro_sede:
        qs = qs.filter(sede_servicio__sede__cod_sede=filtro_sede)
    if filtro_servicio:
        qs = qs.filter(sede_servicio__servicio__cod_servicio=filtro_servicio)
    if filtro_estado:
        qs = qs.filter(estado=filtro_estado)

    # Contadores para el resumen
    todos = Turno.objects.filter(fecha_turno=fecha_seleccionada)
    resumen = {
        'total': todos.count(),
        'en_espera': todos.filter(estado='en_espera').count(),
        'llamando': todos.filter(estado='llamando').count(),
        'en_atencion': todos.filter(estado='en_atencion').count(),
        'atendido': todos.filter(estado='atendido').count(),
        'no_asistio': todos.filter(estado='no_asistio').count(),
        'cancelado': todos.filter(estado='cancelado').count(),
    }

    contexto = {
        'turnos': qs,
        'resumen': resumen,
        'sedes': Sede.objects.filter(activo=True).order_by('nombre'),
        'servicios_lista': Servicio.objects.filter(activo=True).order_by('nombre'),
        'filtro_sede': filtro_sede,
        'filtro_servicio': filtro_servicio,
        'filtro_estado': filtro_estado,
        'fecha_seleccionada': fecha_seleccionada,
        'fecha_seleccionada_str': fecha_seleccionada.strftime('%Y-%m-%d'),
        'es_hoy': es_hoy,
    }
    return render(request, 'panel_operador.html', contexto)


@operador_requerido
@require_POST
def actualizar_estado_turno(request):
    """
    Actualiza el estado de un turno desde el panel del operador.

    Recibe por POST:
        turno_id    — UUID del turno
        nuevo_estado — uno de: llamando, en_atencion, atendido, no_asistio
    """
    from django.utils import timezone

    turno_id = request.POST.get('turno_id')
    nuevo_estado = request.POST.get('nuevo_estado', '')

    if nuevo_estado not in ESTADOS_VALIDOS:
        messages.error(request, 'Estado no válido.')
        return redirect('panel_operador')

    turno = get_object_or_404(Turno, pk=turno_id)

    # Actualizar el estado
    turno.estado = nuevo_estado

    # Asignar operador si aún no tiene
    if not turno.operador:
        turno.operador = request.user

    # Registrar timestamps según la transición
    if nuevo_estado == 'en_atencion' and not turno.fecha_inicio_atencion:
        turno.fecha_inicio_atencion = timezone.now()
    elif nuevo_estado in ('atendido', 'no_asistio') and not turno.fecha_fin_atencion:
        turno.fecha_fin_atencion = timezone.now()

    turno.save(update_fields=[
        'estado', 'operador', 'fecha_inicio_atencion', 'fecha_fin_atencion',
    ])

    etiquetas = {
        'llamando': 'Llamando',
        'en_atencion': 'En atención',
        'atendido': 'Atendido',
        'no_asistio': 'No asistió',
    }
    messages.success(
        request,
        f'Turno {turno.codigo_visual} actualizado a "{etiquetas[nuevo_estado]}".',
    )
    return redirect('panel_operador')


# =============================================================================
# Vistas del módulo de Farmacia
# =============================================================================

@login_required(login_url='inicio')
def vista_informativa_farmacia(request):
    """
    Vista informativa (acceso remoto desde Home).
    Muestra las sedes de farmacia con personas en espera y tiempo estimado.
    NO permite solicitar turno — requiere QR físico.
    """
    sedes = SedeFarmacia.objects.filter(activo=True).order_by('ciudad', 'nombre')
    hoy = timezone.localdate()

    sedes_info = []
    for sede in sedes:
        en_espera = Turno.objects.filter(
            sede_farmacia=sede,
            tipo_servicio='FARMACIA',
            fecha_turno=hoy,
            estado='en_espera',
        ).count()
        sedes_info.append({
            'sede': sede,
            'en_espera': en_espera,
            'tiempo_estimado': en_espera * 10,
        })

    return render(request, 'farmacia_info.html', {'sedes_info': sedes_info})


def pantalla_farmacia_sede(request, sede_id):
    """
    Vista para la pantalla/TV de una sede de farmacia.
    Muestra el QR dinámico y la cola en vivo.
    No requiere autenticación (pantalla pública).
    """
    sede = get_object_or_404(SedeFarmacia, pk=sede_id, activo=True)
    hoy = timezone.localdate()

    turnos_hoy = (
        Turno.objects
        .filter(sede_farmacia=sede, tipo_servicio='FARMACIA', fecha_turno=hoy)
        .exclude(estado__in=['cancelado'])
        .order_by('consecutivo_diario')
    )

    en_espera = turnos_hoy.filter(estado='en_espera').count()
    atendidos = turnos_hoy.filter(estado='atendido').count()
    turno_actual = turnos_hoy.filter(estado__in=['llamando', 'en_atencion']).first()

    return render(request, 'farmacia_pantalla.html', {
        'sede': sede,
        'en_espera': en_espera,
        'atendidos': atendidos,
        'turno_actual': turno_actual,
        'turnos_hoy': turnos_hoy,
    })


def api_qr_farmacia(request, sede_id):
    """
    API AJAX: genera un nuevo token QR para la sede de farmacia.
    Invalida todos los tokens anteriores de esa sede.
    Devuelve JSON con la URL de validación y la URL de la imagen QR.
    """
    sede = get_object_or_404(SedeFarmacia, pk=sede_id, activo=True)

    TokenQRFarmacia.objects.filter(sede_farmacia=sede, activo=True).update(activo=False)

    nuevo_token = TokenQRFarmacia.objects.create(sede_farmacia=sede)

    url_validacion = request.build_absolute_uri(
        f'/farmacia/validar/{sede.id}/{nuevo_token.token}/'
    )
    url_qr_img = request.build_absolute_uri(
        f'/farmacia/qr-image/{sede.id}/{nuevo_token.token}/'
    )

    return JsonResponse({
        'token': str(nuevo_token.token),
        'url_validacion': url_validacion,
        'url_qr_img': url_qr_img,
    })


def qr_image_farmacia(request, sede_id, token):
    """
    Genera la imagen QR en memoria y la devuelve como PNG.
    No guarda nada en disco.
    """
    sede = get_object_or_404(SedeFarmacia, pk=sede_id)
    url_validacion = request.build_absolute_uri(
        f'/farmacia/validar/{sede.id}/{token}/'
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url_validacion)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#0960ae', back_color='white')

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return HttpResponse(buffer.getvalue(), content_type='image/png')


@login_required(login_url='inicio')
def validar_token_farmacia(request, sede_id, token):
    """
    Valida el token QR escaneado por el usuario.

    GET  — Si el token es válido (<60s, activo), muestra formulario de turno.
    POST — Genera el turno con prefijo FAR-.
    """
    sede = get_object_or_404(SedeFarmacia, pk=sede_id, activo=True)

    try:
        token_obj = TokenQRFarmacia.objects.get(
            sede_farmacia=sede, token=token, activo=True
        )
    except TokenQRFarmacia.DoesNotExist:
        return render(request, 'farmacia_validar.html', {
            'sede': sede, 'valido': False,
            'error': 'El código ha expirado o es inválido. '
                     'Por favor, escanee el código actual de la pantalla.',
        })

    ahora = timezone.now()
    if (ahora - token_obj.fecha_creacion).total_seconds() > 60:
        token_obj.activo = False
        token_obj.save(update_fields=['activo'])
        return render(request, 'farmacia_validar.html', {
            'sede': sede, 'valido': False,
            'error': 'El código ha expirado. '
                     'Por favor, escanee el código actual de la pantalla.',
        })

    if request.method == 'POST':
        hoy = timezone.localdate()

        ya_tiene = Turno.objects.filter(
            usuario=request.user,
            sede_farmacia=sede,
            tipo_servicio='FARMACIA',
            fecha_turno=hoy,
            estado='en_espera',
        ).exists()
        if ya_tiene:
            messages.error(request, 'Ya tienes un turno activo en esta sede.')
            return redirect('farmacia_info')

        max_consecutivo = (
            Turno.objects
            .filter(sede_farmacia=sede, tipo_servicio='FARMACIA', fecha_turno=hoy)
            .aggregate(Max('consecutivo_diario'))['consecutivo_diario__max']
        ) or 0
        nuevo_consecutivo = max_consecutivo + 1
        codigo_visual = f'FAR-{nuevo_consecutivo:03d}'

        turno = Turno.objects.create(
            tipo_servicio='FARMACIA',
            sede_farmacia=sede,
            sede_servicio=None,
            fecha_turno=hoy,
            consecutivo_diario=nuevo_consecutivo,
            codigo_visual=codigo_visual,
            estado='en_espera',
            usuario=request.user,
        )
        return redirect('farmacia_ticket', turno_id=turno.pk)

    return render(request, 'farmacia_validar.html', {
        'sede': sede, 'valido': True, 'token': token,
    })


@login_required(login_url='inicio')
def ticket_farmacia(request, turno_id):
    """
    Ticket digital del turno de farmacia.
    Muestra el número asignado y la posición en la cola.
    """
    turno = get_object_or_404(Turno, pk=turno_id, tipo_servicio='FARMACIA')

    if turno.usuario != request.user:
        messages.error(request, 'No tienes permiso para ver este turno.')
        return redirect('farmacia_info')

    hoy = turno.fecha_turno
    posicion = Turno.objects.filter(
        sede_farmacia=turno.sede_farmacia,
        tipo_servicio='FARMACIA',
        fecha_turno=hoy,
        estado='en_espera',
        consecutivo_diario__lt=turno.consecutivo_diario,
    ).count() + 1

    total_espera = Turno.objects.filter(
        sede_farmacia=turno.sede_farmacia,
        tipo_servicio='FARMACIA',
        fecha_turno=hoy,
        estado='en_espera',
    ).count()

    turno_actual = Turno.objects.filter(
        sede_farmacia=turno.sede_farmacia,
        tipo_servicio='FARMACIA',
        fecha_turno=hoy,
        estado__in=['llamando', 'en_atencion'],
    ).first()

    return render(request, 'farmacia_ticket.html', {
        'turno': turno,
        'posicion': posicion,
        'total_espera': total_espera,
        'turno_actual': turno_actual,
        'tiempo_estimado': posicion * 10,
    })


# =============================================================================
# Vistas del módulo de Atención al Cliente (PQRS)
# =============================================================================

@login_required(login_url='inicio')
def atencion_cliente(request):
    """Landing page del módulo de Atención al Cliente."""
    return render(request, 'atencion_cliente.html')


@login_required(login_url='inicio')
def crear_pqrs(request):
    """Formulario para radicar una nueva PQRS."""
    if request.method == 'POST':
        formulario = PQRSForm(request.POST)
        if formulario.is_valid():
            pqrs = formulario.save(commit=False)
            pqrs.usuario = request.user
            pqrs.save()
            messages.success(
                request,
                f'Su PQRS ha sido radicada con el número: '
                f'{pqrs.numero_radicado}',
            )
            return redirect('mis_pqrs')
    else:
        formulario = PQRSForm()
    return render(request, 'crear_pqrs.html', {'formulario': formulario})


@login_required(login_url='inicio')
def mis_pqrs(request):
    """Listado de PQRS del usuario autenticado."""
    solicitudes = PQRS.objects.filter(usuario=request.user)
    return render(request, 'mis_pqrs.html', {'solicitudes': solicitudes})


@admin_requerido
def admin_pqrs(request):
    """Panel de administración de PQRS."""
    estado_filtro = request.GET.get('estado', '')
    solicitudes = PQRS.objects.select_related('usuario', 'sede').all()
    if estado_filtro:
        solicitudes = solicitudes.filter(estado=estado_filtro)
    return render(request, 'admin_pqrs.html', {
        'solicitudes': solicitudes,
        'estado_filtro': estado_filtro,
    })


@admin_requerido
@require_POST
def admin_actualizar_pqrs(request, pk):
    """Actualiza el estado de una PQRS desde el panel de administración."""
    pqrs = get_object_or_404(PQRS, pk=pk)
    nuevo_estado = request.POST.get('estado', '')
    estados_validos = dict(PQRS.ESTADO_CHOICES)
    if nuevo_estado not in estados_validos:
        messages.error(request, 'Estado no válido.')
        return redirect('admin_pqrs')
    pqrs.estado = nuevo_estado
    pqrs.save(update_fields=['estado'])
    messages.success(
        request,
        f'La PQRS {pqrs.numero_radicado} fue actualizada a '
        f'"{estados_validos[nuevo_estado]}".',
    )
    return redirect('admin_pqrs')


@admin_requerido
def detalle_pqrs_admin(request, pk):
    """Vista de detalle de una PQRS para el administrador."""
    pqrs = get_object_or_404(
        PQRS.objects.select_related('usuario', 'sede'), pk=pk
    )
    if request.method == 'POST':
        nuevo_estado = request.POST.get('estado', '')
        estados_validos = dict(PQRS.ESTADO_CHOICES)
        if nuevo_estado in estados_validos:
            pqrs.estado = nuevo_estado
            pqrs.save(update_fields=['estado'])
            messages.success(
                request,
                f'Estado actualizado a "{estados_validos[nuevo_estado]}".',
            )
        else:
            messages.error(request, 'Estado no válido.')
        return redirect('detalle_pqrs_admin', pk=pk)
    return render(request, 'detalle_pqrs_admin.html', {'pqrs': pqrs})


# =============================================================================
# Panel de Estadísticas y Reportes
# =============================================================================

@admin_requerido
def panel_estadisticas(request):
    """Dashboard de estadísticas con filtros de sede y rango temporal."""
    hoy = timezone.localdate()

    # ── Filtros ──────────────────────────────────────────────────────────────
    sede_filtro = request.GET.get('sede', '')
    rango_filtro = request.GET.get('rango', 'mes')

    # Calcular rango de fechas
    if rango_filtro == 'hoy':
        fecha_desde = hoy
    elif rango_filtro == '7dias':
        fecha_desde = hoy - timedelta(days=7)
    elif rango_filtro == 'anio':
        fecha_desde = hoy - timedelta(days=365)
    else:  # mes (default)
        fecha_desde = hoy.replace(day=1)

    # ── Queryset base de turnos ──────────────────────────────────────────────
    turnos_qs = Turno.objects.filter(fecha_turno__gte=fecha_desde)

    # Aplicar filtro de sede (individual o agregado)
    if sede_filtro == 'todas_medicas':
        turnos_qs = turnos_qs.filter(sede_servicio__isnull=False)
    elif sede_filtro == 'todas_farmacia':
        turnos_qs = turnos_qs.filter(sede_farmacia__isnull=False)
    elif sede_filtro.startswith('med_'):
        cod = sede_filtro[4:]
        turnos_qs = turnos_qs.filter(sede_servicio__sede__cod_sede=cod)
    elif sede_filtro.startswith('far_'):
        uid = sede_filtro[4:]
        turnos_qs = turnos_qs.filter(sede_farmacia__id=uid)

    # ── KPIs ─────────────────────────────────────────────────────────────────
    total_turnos = turnos_qs.count()
    atendidos = turnos_qs.filter(estado='atendido').count()
    no_asistio = turnos_qs.filter(estado='no_asistio').count()
    cancelados = turnos_qs.filter(estado='cancelado').count()
    pqrs_pendientes = PQRS.objects.filter(estado='radicado').count()

    eficiencia = round(atendidos / total_turnos * 100, 1) if total_turnos else 0
    tasa_inasistencia = round(no_asistio / total_turnos * 100, 1) if total_turnos else 0
    tasa_cancelacion = round(cancelados / total_turnos * 100, 1) if total_turnos else 0

    # ── Distribución por servicio ────────────────────────────────────────────
    distribucion_raw = (
        turnos_qs
        .values('tipo_servicio')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    tipo_labels = dict(Turno.TIPO_SERVICIO_CHOICES)
    tipo_colors = {
        'MEDICINA': 'blue',
        'LABORATORIO': 'purple',
        'VACUNACION': 'teal',
        'FARMACIA': 'amber',
    }
    distribucion = []
    for item in distribucion_raw:
        ts = item['tipo_servicio']
        pct = round(item['total'] / total_turnos * 100, 1) if total_turnos else 0
        distribucion.append({
            'tipo': ts,
            'label': tipo_labels.get(ts, ts),
            'total': item['total'],
            'porcentaje': pct,
            'porcentaje_safe': max(pct, 2) if pct > 0 else 0,
            'color': tipo_colors.get(ts, 'gray'),
        })

    # ── PQRS Insights ────────────────────────────────────────────────────────
    pqrs_insights = (
        PQRS.objects
        .values('tipo')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    tipo_pqrs_labels = dict(PQRS.TIPO_CHOICES)
    insights = []
    total_pqrs_all = sum(i['total'] for i in pqrs_insights) or 1
    for item in pqrs_insights:
        pct = round(item['total'] / total_pqrs_all * 100, 1)
        insights.append({
            'tipo': item['tipo'],
            'label': tipo_pqrs_labels.get(item['tipo'], item['tipo']),
            'total': item['total'],
            'porcentaje': pct,
            'porcentaje_safe': max(pct, 2) if pct > 0 else 0,
        })

    # ── Opciones para los filtros ────────────────────────────────────────────
    sedes_medicas = Sede.objects.filter(activo=True).order_by('nombre')
    sedes_farmacia = SedeFarmacia.objects.filter(activo=True).order_by('nombre')

    contexto = {
        'total_turnos': total_turnos,
        'atendidos': atendidos,
        'no_asistio': no_asistio,
        'cancelados': cancelados,
        'eficiencia': eficiencia,
        'tasa_inasistencia': tasa_inasistencia,
        'tasa_cancelacion': tasa_cancelacion,
        'pqrs_pendientes': pqrs_pendientes,
        'distribucion': distribucion,
        'insights': insights,
        'sedes_medicas': sedes_medicas,
        'sedes_farmacia': sedes_farmacia,
        'sede_filtro': sede_filtro,
        'rango_filtro': rango_filtro,
    }
    return render(request, 'panel_estadisticas.html', contexto)


# =============================================================================
# Exportar PDF del Panel de Estadísticas
# =============================================================================

@admin_requerido
def exportar_pdf_estadisticas(request):
    """Genera y devuelve un reporte PDF con los mismos filtros del dashboard."""
    hoy = timezone.localdate()

    # ── Filtros (misma lógica que panel_estadisticas) ─────────────────────────
    sede_filtro = request.GET.get('sede', '')
    rango_filtro = request.GET.get('rango', 'mes')

    rango_labels = {
        'hoy': 'Hoy',
        '7dias': 'Últimos 7 días',
        'mes': 'Este mes',
        'anio': 'Último año',
    }

    if rango_filtro == 'hoy':
        fecha_desde = hoy
    elif rango_filtro == '7dias':
        fecha_desde = hoy - timedelta(days=7)
    elif rango_filtro == 'anio':
        fecha_desde = hoy - timedelta(days=365)
    else:  # mes (default)
        fecha_desde = hoy.replace(day=1)

    # ── Queryset base ─────────────────────────────────────────────────────────
    turnos_qs = Turno.objects.filter(fecha_turno__gte=fecha_desde)

    sede_label = 'Todas las sedes'
    if sede_filtro == 'todas_medicas':
        turnos_qs = turnos_qs.filter(sede_servicio__isnull=False)
        sede_label = 'Todas las sedes médicas'
    elif sede_filtro == 'todas_farmacia':
        turnos_qs = turnos_qs.filter(sede_farmacia__isnull=False)
        sede_label = 'Todas las sedes de farmacia'
    elif sede_filtro.startswith('med_'):
        cod = sede_filtro[4:]
        turnos_qs = turnos_qs.filter(sede_servicio__sede__cod_sede=cod)
        try:
            sede_label = Sede.objects.get(cod_sede=cod).nombre
        except Sede.DoesNotExist:
            sede_label = cod
    elif sede_filtro.startswith('far_'):
        uid = sede_filtro[4:]
        turnos_qs = turnos_qs.filter(sede_farmacia__id=uid)
        try:
            sede_label = SedeFarmacia.objects.get(id=uid).nombre
        except SedeFarmacia.DoesNotExist:
            sede_label = uid

    # ── KPIs ─────────────────────────────────────────────────────────────────
    total_turnos = turnos_qs.count()
    atendidos = turnos_qs.filter(estado='atendido').count()
    no_asistio = turnos_qs.filter(estado='no_asistio').count()
    cancelados = turnos_qs.filter(estado='cancelado').count()
    pqrs_pendientes = PQRS.objects.filter(estado='radicado').count()

    eficiencia = round(atendidos / total_turnos * 100, 1) if total_turnos else 0
    tasa_inasistencia = round(no_asistio / total_turnos * 100, 1) if total_turnos else 0
    tasa_cancelacion = round(cancelados / total_turnos * 100, 1) if total_turnos else 0

    # ── Distribución por servicio ─────────────────────────────────────────────
    distribucion_raw = (
        turnos_qs
        .values('tipo_servicio')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    tipo_labels = dict(Turno.TIPO_SERVICIO_CHOICES)
    distribucion = []
    for item in distribucion_raw:
        ts = item['tipo_servicio']
        pct = round(item['total'] / total_turnos * 100, 1) if total_turnos else 0
        distribucion.append({
            'label': tipo_labels.get(ts, ts),
            'total': item['total'],
            'porcentaje': pct,
        })

    # ── PQRS Insights ─────────────────────────────────────────────────────────
    pqrs_insights_qs = (
        PQRS.objects
        .values('tipo')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    tipo_pqrs_labels = dict(PQRS.TIPO_CHOICES)
    total_pqrs_all = sum(i['total'] for i in pqrs_insights_qs) or 1
    insights = []
    for item in pqrs_insights_qs:
        pct = round(item['total'] / total_pqrs_all * 100, 1)
        insights.append({
            'label': tipo_pqrs_labels.get(item['tipo'], item['tipo']),
            'total': item['total'],
            'porcentaje': pct,
        })

    # ── Construcción del PDF ──────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    primary_blue = colors.HexColor('#0960ae')
    light_grey = colors.HexColor('#848484')
    dark_grey = colors.HexColor('#515151')
    bg_grey = colors.HexColor('#f3f4f6')

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        fontSize=20,
        textColor=primary_blue,
        spaceAfter=4,
        fontName='Helvetica-Bold',
    )
    style_subtitle = ParagraphStyle(
        'ReportSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=light_grey,
        spaceAfter=2,
        fontName='Helvetica',
    )
    style_section = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=primary_blue,
        spaceBefore=14,
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    style_body = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=9,
        textColor=dark_grey,
        fontName='Helvetica',
        leading=14,
    )
    style_empty = ParagraphStyle(
        'Empty',
        parent=styles['Normal'],
        fontSize=9,
        textColor=light_grey,
        fontName='Helvetica-Oblique',
        alignment=TA_CENTER,
    )

    story = []

    # — Encabezado corporativo —
    story.append(Paragraph('EPS — Centro Médico', style_title))
    story.append(Paragraph('Reporte de Estadísticas Operacionales', style_subtitle))
    story.append(Paragraph(
        f'Generado el: {hoy.strftime("%d de %B de %Y")}  |  '
        f'Sede: {sede_label}  |  '
        f'Período: {rango_labels.get(rango_filtro, rango_filtro)}',
        style_subtitle,
    ))
    story.append(HRFlowable(width='100%', thickness=1.5, color=primary_blue, spaceAfter=10))

    # — KPIs principales —
    story.append(Paragraph('Indicadores Clave de Desempeño (KPIs)', style_section))

    kpi_data = [
        ['Indicador', 'Valor', 'Detalle'],
        ['Total de Turnos', str(total_turnos), '—'],
        ['Turnos Atendidos', str(atendidos), f'{eficiencia}% de eficiencia'],
        ['Inasistencias', str(no_asistio), f'{tasa_inasistencia}% del total'],
        ['Cancelaciones', str(cancelados), f'{tasa_cancelacion}% del total'],
        ['PQRS Pendientes', str(pqrs_pendientes), 'Estado: Radicado'],
    ]
    kpi_table = Table(kpi_data, colWidths=[8 * cm, 3.5 * cm, 6 * cm])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_blue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TEXTCOLOR', (0, 1), (-1, -1), dark_grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, bg_grey]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica-Bold'),
    ]))
    story.append(kpi_table)

    # — Distribución por tipo de servicio —
    story.append(Paragraph('Distribución por Tipo de Servicio', style_section))
    if distribucion:
        dist_data = [['Tipo de Servicio', 'Turnos', 'Porcentaje']]
        for d in distribucion:
            dist_data.append([d['label'], str(d['total']), f"{d['porcentaje']}%"])
        dist_table = Table(dist_data, colWidths=[9.5 * cm, 3.5 * cm, 4.5 * cm])
        dist_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_blue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TEXTCOLOR', (0, 1), (-1, -1), dark_grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, bg_grey]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ]))
        story.append(dist_table)
    else:
        story.append(Paragraph('No hay datos de turnos para el período y sede seleccionados.', style_empty))

    # — PQRS por tipo —
    story.append(Paragraph('Resumen de PQRS por Tipo', style_section))
    if insights:
        pqrs_data = [['Tipo de PQRS', 'Cantidad', 'Porcentaje']]
        for i in insights:
            pqrs_data.append([i['label'], str(i['total']), f"{i['porcentaje']}%"])
        pqrs_table = Table(pqrs_data, colWidths=[9.5 * cm, 3.5 * cm, 4.5 * cm])
        pqrs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_blue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TEXTCOLOR', (0, 1), (-1, -1), dark_grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, bg_grey]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ]))
        story.append(pqrs_table)
    else:
        story.append(Paragraph('No se han registrado PQRS en el sistema.', style_empty))

    # — Pie de página informativo —
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=light_grey, spaceAfter=6))
    story.append(Paragraph(
        'Este reporte fue generado automáticamente por el sistema de gestión EPS — Centro Médico. '
        'Para uso interno únicamente.',
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, textColor=light_grey,
                       fontName='Helvetica', alignment=TA_CENTER),
    ))

    doc.build(story)
    buffer.seek(0)

    nombre_archivo = f'reporte_estadisticas_{hoy.strftime("%Y%m%d")}.pdf'
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


# =============================================================================
# Chatbot de Navegación — API View (Groq vía OpenAI SDK)
# =============================================================================

# ── Configuración del proveedor ─────────────────────────────────────────────────────────
# Proveedor: Groq (free tier) — API compatible con OpenAI SDK ya instalado.
# Crea tu clave gratuita en: https://console.groq.com/keys
CHATBOT_MODEL       = 'llama-3.1-8b-instant'
CHATBOT_BASE_URL    = 'https://api.groq.com/openai/v1'
CHATBOT_API_KEY_ENV = 'GROQ_API_KEY'

# ── Instrucciones del sistema ─────────────────────────────────────────────────
CHATBOT_SYSTEM_PROMPT = """\
Eres el asistente virtual de "Turnero", un sistema de gestión de turnos y atención médica. Tu único objetivo es guiar a los usuarios indicándoles a qué sección del sistema deben dirigirse según lo que necesiten.

ESTRUCTURA DEL SITIO (A dónde debes enviarlos):
- Si buscan sacar una cita médica o ver a un doctor -> Diles que vayan a la sección "Consultas Médicas".
- Si preguntan por entrega de medicamentos, medicinas o recetas -> Diles que vayan a la sección "Farmacia".
- Si necesitan vacunas, inyecciones, exámenes de laboratorio o toma de muestras -> Diles que vayan a la sección "Procedimientos Clínicos".
- Si quieren poner una queja, reclamo, sugerencia o hacer una pregunta general (PQRS) -> Diles que vayan a la sección "Atención al Cliente".
- Si preguntan por reportes o métricas -> Diles que vayan al "Panel de Estadísticas" (aclara que es solo para administradores).

REGLAS ESTRICTAS DE COMPORTAMIENTO:
1. Sé extremadamente breve y directo. Tu respuesta máxima debe ser de 2 oraciones.
2. No inventes enlaces ni URLs. Solo menciona el nombre de la sección entre comillas.
3. Responde siempre en un tono amable, servicial y en español de Colombia.
4. Si el usuario te pregunta algo fuera de estos temas (clima, recetas de cocina, historia, etc.), dile educadamente que solo puedes ayudarle a navegar por el sistema de Turnero.
"""




@require_POST
@login_required
def chatbot_api(request):
    """
    Endpoint POST /chatbot/api/
    Payload JSON  : { "mensaje": "texto del usuario" }
    Respuesta JSON: { "respuesta": "texto del bot" }
    """
    # ── Leer cuerpo JSON ──────────────────────────────────────────────────────
    try:
        body = json.loads(request.body)
        mensaje_usuario = str(body.get('mensaje', '')).strip()
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)

    if not mensaje_usuario:
        return JsonResponse({'respuesta': 'Por favor escribe un mensaje para que pueda ayudarte.'})

    # Limitar longitud de entrada
    mensaje_usuario = mensaje_usuario[:500]

    # ── Verificar API key ─────────────────────────────────────────────────────
    api_key = os.environ.get(CHATBOT_API_KEY_ENV, '')
    if not api_key:
        return JsonResponse(
            {'respuesta': 'El asistente no está configurado aún. Contacta al administrador.'},
            status=503,
        )

    # ── Llamada a DeepSeek vía OpenAI SDK ─────────────────────────────────────
    try:
        client = DeepSeekClient(
            api_key=api_key,
            base_url=CHATBOT_BASE_URL,
        )
        completion = client.chat.completions.create(
            model=CHATBOT_MODEL,
            messages=[
                {'role': 'system', 'content': CHATBOT_SYSTEM_PROMPT},
                {'role': 'user',   'content': mensaje_usuario},
            ],
            max_tokens=200,
            temperature=0.3,
            stream=False,
        )
        respuesta_texto = completion.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        print(f'[chatbot_api] Error DeepSeek: {type(exc).__name__}: {exc}')
        return JsonResponse(
            {'respuesta': 'En este momento no puedo responder. Por favor, intenta más tarde.'},
            status=200,
        )

    return JsonResponse({'respuesta': respuesta_texto})