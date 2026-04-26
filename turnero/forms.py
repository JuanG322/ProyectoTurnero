"""
forms.py — Formularios del módulo turnero.
Define el formulario de solicitud de consulta médica con validaciones personalizadas.
"""

from datetime import timedelta, datetime as dt

from django import forms
from django.utils import timezone

from .models import Sede, SedeServicio, Servicio


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

    No hereda de ModelForm porque el modelo Turno requiere campos
    calculados (consecutivo_diario, codigo_visual, sede_servicio)
    que se resuelven en la vista antes de guardar.
    """

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
        Validación cruzada: si la consulta es para hoy, la franja horaria
        seleccionada no debe corresponder a una hora ya transcurrida.
        """
        cleaned = super().clean()
        fecha = cleaned.get('fecha_turno')
        hora_str = cleaned.get('hora_consulta')

        if fecha and hora_str:
            hoy = timezone.localdate()
            if fecha == hoy:
                # Hora actual en la zona horaria de Bogotá
                ahora = timezone.localtime().time()
                hora_seleccionada = dt.strptime(hora_str, '%H:%M').time()
                if hora_seleccionada <= ahora:
                    self.add_error(
                        'hora_consulta',
                        'La franja seleccionada ya pasó. '
                        'Por favor elige una hora futura para hoy.'
                    )
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
        """Valida que el código de sede no exista ya en la base de datos."""
        codigo = self.cleaned_data.get('cod_sede')
        if codigo and Sede.objects.filter(cod_sede=codigo).exists():
            raise forms.ValidationError(
                f'Ya existe una sede con el código "{codigo}". '
                'Por favor ingrese un código diferente.'
            )
        return codigo


class ServicioForm(forms.ModelForm):
    """
    Formulario para crear un nuevo servicio.
    Valida que el código de servicio no exista previamente en la BD.
    """

    class Meta:
        model = Servicio
        fields = ['cod_servicio', 'nombre']
        labels = {
            'cod_servicio': 'Código de servicio',
            'nombre': 'Nombre del servicio',
        }
        help_texts = {
            'cod_servicio': 'Código único alfanumérico (máx. 10 caracteres).',
        }

    def clean_cod_servicio(self):
        """Valida que el código de servicio no exista ya en la base de datos."""
        codigo = self.cleaned_data.get('cod_servicio')
        if codigo and Servicio.objects.filter(cod_servicio=codigo).exists():
            raise forms.ValidationError(
                f'Ya existe un servicio con el código "{codigo}". '
                'Por favor ingrese un código diferente.'
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
        """Valida que la combinación sede + servicio no esté registrada."""
        cleaned = super().clean()
        sede = cleaned.get('sede')
        servicio = cleaned.get('servicio')

        if sede and servicio:
            if SedeServicio.objects.filter(sede=sede, servicio=servicio).exists():
                raise forms.ValidationError(
                    f'La sede "{sede}" ya tiene vinculado el servicio "{servicio}". '
                    'No se puede duplicar esta combinación.'
                )
        return cleaned

