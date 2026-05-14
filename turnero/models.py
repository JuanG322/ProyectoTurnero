import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class UsuarioManager(BaseUserManager):
    def create_user(self, email, num_documento, nombre, password=None, **extra_fields):
        if not email:
            raise ValueError('El usuario debe tener un correo electrónico')

        email = self.normalize_email(email)
        user = self.model(
            email=email,
            num_documento=num_documento,
            nombre=nombre,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, num_documento, nombre, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('rol', 'admin')

        # Aquí llamamos a create_user con los nombres correctos
        return self.create_user(email, num_documento, nombre, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    TIPO_DOC_CHOICES = [
        ('cc', 'Cédula de Ciudadanía'),
        ('ti', 'Tarjeta de Identidad'),
        ('ce', 'Cédula de Extranjería'),
    ]

    id_usuario = models.AutoField(primary_key=True, db_column='id_usuario')
    num_documento = models.CharField(max_length=20, unique=True, db_column='num_documento')
    tipo_documento = models.CharField(max_length=5, choices=TIPO_DOC_CHOICES, db_column='tipo_documento')
    nombre = models.CharField(max_length=100, db_column='nombre')
    email = models.EmailField(max_length=100, unique=True, db_column='email')
    rol = models.CharField(max_length=20, default='paciente', db_column='rol')

    activo = models.BooleanField(default=True, db_column='activo')
    is_active = models.BooleanField(default=True, db_column='is_active')
    is_staff = models.BooleanField(default=False, db_column='is_staff')
    is_superuser = models.BooleanField(default=False, db_column='is_superuser')
    last_login = models.DateTimeField(null=True, blank=True, db_column='last_login')
    password = models.CharField(max_length=128, db_column='password')

    objects = UsuarioManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['num_documento', 'nombre']

    class Meta:
        db_table = 'USUARIOS'

    def __str__(self):
        return f"{self.nombre} ({self.num_documento})"


# 1. TABLAS MAESTRAS -------------------------

class Sede(models.Model):
    cod_sede = models.CharField(max_length=10, primary_key=True)
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200, default='Sin dirección')
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'SEDES'

    def __str__(self):
        return self.nombre


class Servicio(models.Model):
    CATEGORIA_CHOICES = [
        ('MEDICINA', 'Medicina'),
        ('LABORATORIO', 'Laboratorio'),
        ('VACUNACION', 'Vacunación'),
    ]

    cod_servicio = models.CharField(max_length=10, primary_key=True)
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(
        max_length=15, choices=CATEGORIA_CHOICES, default='MEDICINA',
        help_text='Categoría a la que pertenece el servicio.',
    )
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'SERVICIOS'

    def __str__(self):
        return self.nombre


# 2. TABLAS INTERMEDIAS Y DEPENDIENTES --------------------------

class SedeServicio(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, db_column='cod_sede')
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE, db_column='cod_servicio')
    prefijo = models.CharField(max_length=5)

    class Meta:
        db_table = 'SEDE_SERVICIOS'
        unique_together = ('sede', 'servicio')

    def __str__(self):
        return f"{self.sede.nombre} - {self.servicio.nombre}"


class Ventanilla(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sede = models.ForeignKey(Sede, on_delete=models.CASCADE, db_column='cod_sede')
    cod_ventanilla = models.CharField(max_length=10)
    descripcion = models.CharField(max_length=100, null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'VENTANILLAS'
        unique_together = ('sede', 'cod_ventanilla')


# 3. RELACIÓN 1 A 1

class Configuracion(models.Model):
    sede_servicio = models.OneToOneField(SedeServicio, on_delete=models.CASCADE, primary_key=True)
    tiempo_promedio_atencion_min = models.IntegerField(default=30)
    horario_inicio = models.TimeField()
    horario_fin = models.TimeField()
    tiempo_espera_actual_min = models.IntegerField(default=0)
    ultima_actualizacion_cache = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'CONFIGURACIONES'


# 3. MODELOS DE FARMACIA -----------------------------------------------

class SedeFarmacia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    ciudad = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'SEDES_FARMACIA'

    def __str__(self):
        return f"{self.nombre} — {self.ciudad}"


class TokenQRFarmacia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sede_farmacia = models.ForeignKey(
        SedeFarmacia, on_delete=models.CASCADE, related_name='tokens_qr'
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'TOKENS_QR_FARMACIA'

    def __str__(self):
        return f"Token {self.token} — {self.sede_farmacia.nombre}"


# 4. TABLAS DE MOVIMIENTO (Transaccionales) ----------------------------

class TokenRecuperacion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        db_column='num_documento',
        to_field='num_documento'
    )
    token_hash = models.CharField(max_length=128)
    fecha_expiracion = models.DateTimeField()
    usado = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'TOKENS_RECUPERACION'
        unique_together = ('usuario', 'token_hash')

class Turno(models.Model):
    TIPO_SERVICIO_CHOICES = [
        ('MEDICINA', 'Medicina'),
        ('LABORATORIO', 'Laboratorio'),
        ('VACUNACION', 'Vacunación'),
        ('FARMACIA', 'Farmacia'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tipo_servicio = models.CharField(
        max_length=20, choices=TIPO_SERVICIO_CHOICES, default='MEDICINA'
    )
    sede_servicio = models.ForeignKey(
        SedeServicio, on_delete=models.PROTECT, null=True, blank=True
    )
    sede_farmacia = models.ForeignKey(
        SedeFarmacia, on_delete=models.PROTECT, null=True, blank=True,
        related_name='turnos'
    )
    fecha_turno = models.DateField()
    hora_cita = models.TimeField(
        null=True, blank=True,
        help_text='Franja horaria de la consulta (intervalos de 15 min).'
    )
    consecutivo_diario = models.IntegerField()

    codigo_visual = models.CharField(max_length=10)
    estado = models.CharField(max_length=20, default='en_espera')

    ventanilla = models.ForeignKey(Ventanilla, on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='turnos_paciente',
        null=True,
        blank=True,
        db_column='num_documento_usuario',
        to_field='num_documento'
    )
    operador = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        related_name='turnos_operador',
        null=True,
        blank=True,
        db_column='num_documento_operador',
        to_field='num_documento'
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio_atencion = models.DateTimeField(null=True, blank=True)
    fecha_fin_atencion = models.DateTimeField(null=True, blank=True)

    alerta_cercania_enviada = models.BooleanField(default=False)
    ultima_notificacion_enviada = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'TURNOS'


class QrToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    turno = models.ForeignKey(Turno, on_delete=models.CASCADE)
    token_qr = models.CharField(max_length=128)
    fecha_expira = models.DateTimeField()
    usado = models.BooleanField(default=False)

    class Meta:
        db_table = 'QR_TOKENS'
        unique_together = ('turno', 'token_qr')


class HistorialEvento(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    turno = models.ForeignKey(Turno, on_delete=models.CASCADE)
    fecha_hora_evento = models.DateTimeField()
    tipo_evento = models.CharField(max_length=20)
    usuario_accion = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='num_documento_accion',
        to_field='num_documento'
    )

    class Meta:
        db_table = 'HISTORIAL_EVENTOS'
        unique_together = ('turno', 'fecha_hora_evento')


    class Roles:
        PACIENTE = 'Paciente'
        OPERADOR = 'Operador'
        ADMIN = 'Administrador'


# 6. ATENCIÓN AL CLIENTE — PQRS -----------------------------------------------

class PQRS(models.Model):
    TIPO_CHOICES = [
        ('peticion', 'Petición'),
        ('queja', 'Queja'),
        ('reclamo', 'Reclamo'),
        ('sugerencia', 'Sugerencia'),
    ]
    ESTADO_CHOICES = [
        ('radicado', 'Radicado'),
        ('en_proceso', 'En proceso'),
        ('resuelto', 'Resuelto'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='pqrs',
        db_column='num_documento_usuario',
        to_field='num_documento',
    )
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    sede = models.ForeignKey(
        Sede, on_delete=models.SET_NULL, null=True, blank=True,
        help_text='Sede donde ocurrió el evento (opcional).',
    )
    asunto = models.CharField(max_length=200)
    descripcion = models.TextField()
    numero_radicado = models.CharField(max_length=20, unique=True, editable=False)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='radicado')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'PQRS'
        ordering = ['-fecha_creacion']

    def save(self, *args, **kwargs):
        if not self.numero_radicado:
            from django.utils import timezone
            year = timezone.localdate().year
            count = PQRS.objects.filter(
                fecha_creacion__year=year
            ).count() + 1
            self.numero_radicado = f'PQRS-{year}-{count:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.numero_radicado} — {self.get_tipo_display()}'