from django.contrib import admin
from .models import Usuario, Sede, Servicio, SedeServicio, Ventanilla, Turno, SedeFarmacia, PQRS

admin.site.register(Usuario)
admin.site.register(Sede)
admin.site.register(Servicio)
admin.site.register(SedeServicio)
admin.site.register(Ventanilla)
admin.site.register(Turno)
admin.site.register(SedeFarmacia)
admin.site.register(PQRS)