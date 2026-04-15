from django.contrib import admin
from .models import Usuario, Sede, Servicio, SedeServicio, Ventanilla, Turno

admin.site.register(Usuario)
admin.site.register(Sede)
admin.site.register(Servicio)
admin.site.register(SedeServicio)
admin.site.register(Ventanilla)
admin.site.register(Turno)