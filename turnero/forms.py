"""
forms.py — Formularios del módulo turnero.
Define el formulario de solicitud de consulta médica con validaciones personalizadas.
"""

from datetime import timedelta, datetime as dt

from django import forms
from django.utils import timezone

from .models import PQRS, Sede, SedeFarmacia, SedeServicio, Servicio, Turno


def _generar_franjas_horarias():
    """
    Genera franjas horarias en intervalos de 15 minutos entre 06:00 y 18:00.
    Retorna una lista de tuplas (valor, etiqueta) para usar en ChoiceField.
    """
    franjas = []
    inicio = dt(2000, 1, 1, 6, 0)   # Apertura: 06:00
    limite = dt(2000, 1, 1, 18, 0)  # Cierre:   18:00
    actual = inicio
    while actual <= limite:
        hora_str = actual.strftime('%H:%M')
        franjas.append((hora_str, hora_str))
        actual += timedelta(minutes=15)
    return franjas


# Franjas precalculadas al cargar el módulo (06:00–18:00, cada 15 min)
FRANJAS_HORARIAS = _generar_franjas_horarias()


class SolicitudConsultaForm(forms.Form):
    """
    Formulario para solicitar una consulta médica.

    Recibe el usuario autenticado como parámetro para validar
    conflictos de doble reserva.
    """

    def __init__(self, *args, usuario=None, categoria=None, **kwargs):
        """Almacena el usuario para las validaciones de doble reserva."""
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.categoria = categoria

        # Filtrar servicios según la categoría seleccionada
        if categoria == 'medicina':
            self.fields['servicio'].queryset = Servicio.objects.filter(
                activo=True, categoria='MEDICINA'
            ).order_by('nombre')
        elif categoria == 'procedimientos':
            self.fields['servicio'].queryset = Servicio.objects.filter(
                activo=True, categoria__in=['LABORATORIO', 'VACUNACION']
            ).order_by('nombre')

    # Selección de sede (solo sedes activas)
    sede = forms.ModelChoiceField(
        queryset=Sede.objects.filter(activo=True).order_by('nombre'),
        label='Sede',
        empty_label='Seleccione una sede...',
        widget=forms.Select(attrs={'id': 'id_sede'}),
    )

    # Selección de servicio (solo servicios activos)
    servicio = forms.ModelChoiceField(
        queryset=Servicio.objects.filter(activo=True).order_by('nombre'),
        label='Servicio',
        empty_label='Seleccione un servicio...',
        widget=forms.Select(attrs={'id': 'id_servicio'}),
    )

    # Fecha de la consulta
    fecha_turno = forms.DateField(
        label='Fecha de la consulta',
        widget=forms.DateInput(attrs={'type': 'date', 'id': 'id_fecha_turno'}),
    )

    # Franja horaria — dropdown con intervalos de 15 minutos
    hora_consulta = forms.ChoiceField(
        choices=[('', 'Seleccione una franja horaria...')] + FRANJAS_HORARIAS,
        label='Hora de la consulta',
        widget=forms.Select(attrs={'id': 'id_hora_consulta'}),
    )

    # -------------------------------------------------------------------------
    # Métodos de validación
    # -------------------------------------------------------------------------

    def clean_fecha_turno(self):
        """
        Valida que la fecha de la consulta no sea anterior a hoy.
        Usa la zona horaria del proyecto (America/Bogota).
        """
        fecha = self.cleaned_data.get('fecha_turno')
        hoy = timezone.localdate()

        if fecha and fecha < hoy:
            raise forms.ValidationError(
                'La fecha de la consulta no puede ser en el pasado. '
                'Seleccione una fecha a partir de hoy.'
            )
        return fecha

    def clean_hora_consulta(self):
        """
        Valida que la franja horaria pertenezca al listado predefinido
        (06:00–18:00, intervalos de 15 minutos).
        """
        hora_str = self.cleaned_data.get('hora_consulta')
        horas_validas = {h for h, _ in FRANJAS_HORARIAS}

        if not hora_str:
            raise forms.ValidationError('Debe seleccionar una franja horaria.')

        if hora_str not in horas_validas:
            raise forms.ValidationError(
                'La franja seleccionada no es válida. Elija una opción del listado.'
            )
        return hora_str

    def clean(self):
        """
        Validación cruzada:
        1. Si la consulta es para hoy, la franja no debe haber pasado.
        2. El mismo usuario no puede tener dos consultas en la misma fecha y hora.
        3. No puede haber dos consultas en la misma SedeServicio, fecha y hora.
        """
        cleaned = super().clean()
        fecha = cleaned.get('fecha_turno')
        hora_str = cleaned.get('hora_consulta')
        sede = cleaned.get('sede')
        servicio = cleaned.get('servicio')

        if not (fecha and hora_str):
            return cleaned

        # Convertir la franja horaria a objeto time para comparar
        hora_obj = dt.strptime(hora_str, '%H:%M').time()

        # --- Validación 1: franja pasada si la fecha es hoy ---
        hoy = timezone.localdate()
        if fecha == hoy:
            ahora = timezone.localtime().time()
            if hora_obj <= ahora:
                self.add_error(
                    'hora_consulta',
                    'La franja seleccionada ya pasó. '
                    'Por favor elige una hora futura para hoy.'
                )
                return cleaned

        # --- Validación 2: doble reserva del mismo usuario ---
        if self.usuario:
            existe_usuario = Turno.objects.filter(
                usuario=self.usuario,
                fecha_turno=fecha,
                hora_cita=hora_obj,
                estado='en_espera',
            ).exists()
            if existe_usuario:
                raise forms.ValidationError(
                    'Ya tienes una consulta agendada para esta fecha y hora. '
                    'Por favor selecciona otra franja horaria.'
                )

        # --- Validación 3: franja ocupada en la misma SedeServicio ---
        if sede and servicio:
            try:
                sede_servicio = SedeServicio.objects.get(
                    sede=sede, servicio=servicio
                )
                existe_franja = Turno.objects.filter(
                    sede_servicio=sede_servicio,
                    fecha_turno=fecha,
                    hora_cita=hora_obj,
                    estado='en_espera',
                ).exists()
                if existe_franja:
                    raise forms.ValidationError(
                        'La franja seleccionada ya está ocupada para este '
                        'servicio en la sede elegida. Elige otra hora o fecha.'
                    )
            except SedeServicio.DoesNotExist:
                # Se maneja en la vista
                pass

        return cleaned


# =============================================================================
# Formularios del Panel de Administración
# =============================================================================

class SedeForm(forms.ModelForm):
    """
    Formulario para crear una nueva sede.
    Valida que el código de sede no exista previamente en la BD.
    """

    class Meta:
        model = Sede
        fields = ['cod_sede', 'nombre', 'direccion']
        labels = {
            'cod_sede': 'Código de sede',
            'nombre': 'Nombre de la sede',
            'direccion': 'Dirección',
        }
        help_texts = {
            'cod_sede': 'Código único alfanumérico (máx. 10 caracteres).',
        }

    def clean_cod_sede(self):
        codigo = self.cleaned_data.get('cod_sede')
        qs = Sede.objects.filter(cod_sede=codigo)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if codigo and qs.exists():
            raise forms.ValidationError(
                f'Ya existe una sede con el código "{codigo}".'
            )
        return codigo


class ServicioForm(forms.ModelForm):
    """
    Formulario para crear un nuevo servicio.
    Valida que el código de servicio no exista previamente en la BD.
    """

    class Meta:
        model = Servicio
        fields = ['cod_servicio', 'nombre', 'categoria']
        labels = {
            'cod_servicio': 'Código de servicio',
            'nombre': 'Nombre del servicio',
            'categoria': 'Categoría',
        }
        help_texts = {
            'cod_servicio': 'Código único alfanumérico (máx. 10 caracteres).',
            'categoria': 'Define en qué módulo aparecerá el servicio.',
        }

    def clean_cod_servicio(self):
        codigo = self.cleaned_data.get('cod_servicio')
        qs = Servicio.objects.filter(cod_servicio=codigo)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if codigo and qs.exists():
            raise forms.ValidationError(
                f'Ya existe un servicio con el código "{codigo}".'
            )
        return codigo


class SedeServicioForm(forms.ModelForm):
    """
    Formulario para vincular una sede con un servicio.
    Incluye el campo prefijo, esencial para la generación de turnos.
    Valida que la combinación sede+servicio no exista ya.
    """

    # Sobreescribir los campos FK para filtrar solo los activos
    sede = forms.ModelChoiceField(
        queryset=Sede.objects.filter(activo=True).order_by('nombre'),
        label='Sede',
        empty_label='Seleccione una sede...',
    )
    servicio = forms.ModelChoiceField(
        queryset=Servicio.objects.filter(activo=True).order_by('nombre'),
        label='Servicio',
        empty_label='Seleccione un servicio...',
    )

    class Meta:
        model = SedeServicio
        fields = ['sede', 'servicio', 'prefijo']
        labels = {
            'prefijo': 'Prefijo del turno',
        }
        help_texts = {
            'prefijo': 'Prefijo para el código visual del turno (ej. LAB, PAG). Máx. 5 caracteres.',
        }

    def clean(self):
        cleaned = super().clean()
        sede = cleaned.get('sede')
        servicio = cleaned.get('servicio')
        if sede and servicio:
            qs = SedeServicio.objects.filter(sede=sede, servicio=servicio)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'La sede "{sede}" ya tiene vinculado el servicio "{servicio}".'
                )
        return cleaned


class SedeFarmaciaForm(forms.ModelForm):
    """Formulario para crear/editar sedes de farmacia."""

    class Meta:
        model = SedeFarmacia
        fields = ['nombre', 'direccion', 'ciudad']
        labels = {
            'nombre': 'Nombre de la sede',
            'direccion': 'Dirección',
            'ciudad': 'Ciudad',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'w-full border border-soft-border dark:border-dark-border '
                         'text-Dark-Grey dark:text-dark-text rounded-full px-5 py-2.5 '
                         'focus:outline-none focus:ring-2 focus:ring-blue '
                         'bg-white dark:bg-dark-card transition-colors',
                'placeholder': 'Ej. Farmacia Central Norte',
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'w-full border border-soft-border dark:border-dark-border '
                         'text-Dark-Grey dark:text-dark-text rounded-full px-5 py-2.5 '
                         'focus:outline-none focus:ring-2 focus:ring-blue '
                         'bg-white dark:bg-dark-card transition-colors',
                'placeholder': 'Ej. Calle 100 #15-20',
            }),
            'ciudad': forms.TextInput(attrs={
                'class': 'w-full border border-soft-border dark:border-dark-border '
                         'text-Dark-Grey dark:text-dark-text rounded-full px-5 py-2.5 '
                         'focus:outline-none focus:ring-2 focus:ring-blue '
                         'bg-white dark:bg-dark-card transition-colors',
                'placeholder': 'Ej. Bogotá',
            }),
        }


class PQRSForm(forms.ModelForm):
    """Formulario para radicar una PQRS."""

    INPUT_CSS = (
        'w-full border border-soft-border dark:border-dark-border '
        'text-Dark-Grey dark:text-dark-text rounded-full px-5 py-2.5 '
        'focus:outline-none focus:ring-2 focus:ring-blue '
        'bg-white dark:bg-dark-card transition-colors'
    )
    TEXTAREA_CSS = (
        'w-full border border-soft-border dark:border-dark-border '
        'text-Dark-Grey dark:text-dark-text rounded-2xl px-5 py-3 '
        'focus:outline-none focus:ring-2 focus:ring-blue '
        'bg-white dark:bg-dark-card transition-colors'
    )

    class Meta:
        model = PQRS
        fields = ['tipo', 'sede', 'asunto', 'descripcion']
        labels = {
            'tipo': 'Tipo de solicitud',
            'sede': 'Sede relacionada (opcional)',
            'asunto': 'Asunto',
            'descripcion': 'Descripción detallada',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo'].widget = forms.Select(
            choices=PQRS.TIPO_CHOICES,
            attrs={'class': self.INPUT_CSS},
        )
        self.fields['sede'].widget = forms.Select(
            attrs={'class': self.INPUT_CSS},
        )
        self.fields['sede'].queryset = Sede.objects.filter(activo=True)
        self.fields['sede'].empty_label = '-- Ninguna --'
        self.fields['asunto'].widget = forms.TextInput(
            attrs={'class': self.INPUT_CSS, 'placeholder': 'Resumen breve de su solicitud'},
        )
        self.fields['descripcion'].widget = forms.Textarea(
            attrs={'class': self.TEXTAREA_CSS, 'rows': 5,
                   'placeholder': 'Describa su solicitud en detalle...'},
        )

