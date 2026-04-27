from django.urls import path
from . import views

urlpatterns = [
    # Autenticación
    path('', views.inicio, name='inicio'),
    path('register/', views.registro, name='registro'),
    path('home/', views.home, name='home'),
    path('salir/', views.salir, name='salir'),

    # Módulo de Consultas Médicas
    path('consulta/', views.consultas, name='consultas'),
    path('consulta/solicitar/', views.solicitar_consulta, name='solicitar_consulta'),
    path('consulta/exitosa/', views.consulta_exitosa, name='consulta_exitosa'),
    path('consulta/mis/', views.mis_consultas, name='mis_consultas'),
    path('consulta/cancelar/', views.cancelar_consulta, name='cancelar_consulta'),
    path('consulta/reprogramar/', views.reprogramar_consulta, name='reprogramar_consulta'),
    path('consulta/reprogramar/<uuid:turno_id>/', views.reprogramar_consulta_detalle, name='reprogramar_consulta_detalle'),

    # API — Franjas horarias disponibles (AJAX)
    path('consulta/api/franjas-disponibles/', views.api_franjas_disponibles, name='api_franjas_disponibles'),

    # Panel de Administración (RBAC — solo superusuarios o staff+Administrador)
    path('admin-panel/', views.panel_admin, name='panel_admin'),
    path('admin-panel/sedes/', views.listar_sedes, name='listar_sedes'),
    path('admin-panel/sedes/crear/', views.crear_sede, name='crear_sede'),
    path('admin-panel/servicios/', views.listar_servicios, name='listar_servicios'),
    path('admin-panel/servicios/crear/', views.crear_servicio, name='crear_servicio'),
    path('admin-panel/vinculacion/', views.listar_sede_servicios, name='listar_sede_servicios'),
    path('admin-panel/vinculacion/crear/', views.crear_sede_servicio, name='crear_sede_servicio'),
]