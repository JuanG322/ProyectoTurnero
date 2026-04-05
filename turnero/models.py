import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# ==========================================
# MODELO DE USUARIOS PERSONALIZADO
# ==========================================

class UsuarioManager(BaseUserManager):
    def create_user(self, identificacion, email, nombre_completo, password=None, **extra_fields):
        if not email:
            raise ValueError('El usuario debe tener un correo electrónico')
        
        email = self.normalize_email(email)
        user = self.model(
            num_documento=identificacion,
            email=email,
            nombre=nombre_completo,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, identificacion, email, nombre_completo, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('rol', 'admin')

        return self.create_user(identificacion, email, nombre_completo, password, **extra_fields)

class Usuario(AbstractBaseUser, PermissionsMixin):
    TIPO_DOC_CHOICES = [
        ('cc', 'Cédula de Ciudadanía'),
        ('ti', 'Tarjeta de Identidad'),
        ('ce', 'Cédula de Extranjería'),
    ]

    num_documento = models.CharField(max_length=20, primary_key=True)
    tipo_documento = models.CharField(max_length=5, choices=TIPO_DOC_CHOICES)
    nombre = models.CharField(max_length=100)
    email = models.EmailField(max_length=100, unique=True)
    rol = models.CharField(max_length=20, default='paciente')
    activo = models.BooleanField(default=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UsuarioManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['num_documento', 'nombre']

    class Meta:
        db_table = 'USUARIOS'

    def __str__(self):
        return f"{self.nombre} ({self.num_documento})"


# ==========================================
# 1. TABLAS MAESTRAS
# ==========================================

class Sede(models.Model):
    cod_sede = models.CharField(max_length=10, primary_key=True)
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200, null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'SEDES'

    def __str__(self):
        return self.nombre


class Servicio(models.Model):
    cod_servicio = models.CharField(max_length=10, primary_key=True)
    nombre = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'SERVICIOS'

    def __str__(self):
        return self.nombre

# ==========================================
# 2. TABLAS INTERMEDIAS Y DEPENDIENTES
# ==========================================

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

# ==========================================
# 3. RELACIÓN 1 A 1
# ==========================================

class Configuracion(models.Model):
    sede_servicio = models.OneToOneField(SedeServicio, on_delete=models.CASCADE, primary_key=True)
    tiempo_promedio_atencion_min = models.IntegerField(default=30)
    horario_inicio = models.TimeField()
    horario_fin = models.TimeField()
    tiempo_espera_actual_min = models.IntegerField(default=0)
    ultima_actualizacion_cache = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'CONFIGURACIONES'

# ==========================================
# 4. TABLAS DE MOVIMIENTO (Transaccionales)
# ==========================================

class TokenRecuperacion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, db_column='num_documento')
    token_hash = models.CharField(max_length=128)
    fecha_expiracion = models.DateTimeField()
    usado = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'TOKENS_RECUPERACION'
        unique_together = ('usuario', 'token_hash')


class Turno(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sede_servicio = models.ForeignKey(SedeServicio, on_delete=models.PROTECT) 
    fecha_turno = models.DateField()
    consecutivo_diario = models.IntegerField()
    
    codigo_visual = models.CharField(max_length=10)
    estado = models.CharField(max_length=20, default='en_espera')
    
    ventanilla = models.ForeignKey(Ventanilla, on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='turnos_paciente', null=True, blank=True, db_column='num_documento_usuario')
    operador = models.ForeignKey(Usuario, on_delete=models.SET_NULL, related_name='turnos_operador', null=True, blank=True, db_column='num_documento_operador')
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_inicio_atencion = models.DateTimeField(null=True, blank=True)
    fecha_fin_atencion = models.DateTimeField(null=True, blank=True)
    
    alerta_cercania_enviada = models.BooleanField(default=False)
    ultima_notificacion_enviada = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'TURNOS'
        unique_together = ('sede_servicio', 'fecha_turno', 'consecutivo_diario')


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
    usuario_accion = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, db_column='num_documento_accion')

    class Meta:
        db_table = 'HISTORIAL_EVENTOS'
        unique_together = ('turno', 'fecha_hora_evento')