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

    # Módulo de Procedimientos Clínicos (Laboratorio + Vacunación)
    path('procedimientos/', views.procedimientos, name='procedimientos'),
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
    path('admin-panel/sedes/<str:pk>/editar/', views.editar_sede, name='editar_sede'),
    path('admin-panel/sedes/<str:pk>/eliminar/', views.eliminar_sede, name='eliminar_sede'),
    path('admin-panel/servicios/', views.listar_servicios, name='listar_servicios'),
    path('admin-panel/servicios/crear/', views.crear_servicio, name='crear_servicio'),
    path('admin-panel/servicios/<str:pk>/editar/', views.editar_servicio, name='editar_servicio'),
    path('admin-panel/servicios/<str:pk>/eliminar/', views.eliminar_servicio, name='eliminar_servicio'),
    path('admin-panel/vinculacion/', views.listar_sede_servicios, name='listar_sede_servicios'),
    path('admin-panel/vinculacion/crear/', views.crear_sede_servicio, name='crear_sede_servicio'),
    path('admin-panel/vinculacion/<uuid:pk>/editar/', views.editar_sede_servicio, name='editar_sede_servicio'),
    path('admin-panel/vinculacion/<uuid:pk>/eliminar/', views.eliminar_sede_servicio, name='eliminar_sede_servicio'),
    path('admin-panel/farmacias/', views.listar_sedes_farmacia, name='listar_sedes_farmacia'),
    path('admin-panel/farmacias/crear/', views.crear_sede_farmacia, name='crear_sede_farmacia'),
    path('admin-panel/farmacias/<uuid:pk>/editar/', views.editar_sede_farmacia, name='editar_sede_farmacia'),
    path('admin-panel/farmacias/<uuid:pk>/eliminar/', views.eliminar_sede_farmacia, name='eliminar_sede_farmacia'),

    # Módulo de Farmacia (QR dinámico + presencia física)
    path('farmacia/', views.vista_informativa_farmacia, name='farmacia_info'),
    path('farmacia/pantalla/<uuid:sede_id>/', views.pantalla_farmacia_sede, name='farmacia_pantalla'),
    path('farmacia/api/qr/<uuid:sede_id>/', views.api_qr_farmacia, name='farmacia_api_qr'),
    path('farmacia/qr-image/<uuid:sede_id>/<uuid:token>/', views.qr_image_farmacia, name='farmacia_qr_image'),
    path('farmacia/validar/<uuid:sede_id>/<uuid:token>/', views.validar_token_farmacia, name='farmacia_validar'),
    path('farmacia/ticket/<uuid:turno_id>/', views.ticket_farmacia, name='farmacia_ticket'),

    # Panel de Operador (RBAC — solo superusuarios o staff+Operador)
    path('operador/', views.panel_operador, name='panel_operador'),
    path('operador/actualizar-estado/', views.actualizar_estado_turno, name='actualizar_estado_turno'),

    # Módulo de Atención al Cliente (PQRS)
    path('atencion/', views.atencion_cliente, name='atencion_cliente'),
    path('atencion/pqrs/crear/', views.crear_pqrs, name='crear_pqrs'),
    path('atencion/pqrs/mis/', views.mis_pqrs, name='mis_pqrs'),
    path('admin-panel/pqrs/', views.admin_pqrs, name='admin_pqrs'),
    path('admin-panel/pqrs/<uuid:pk>/actualizar/', views.admin_actualizar_pqrs, name='admin_actualizar_pqrs'),
    path('admin-panel/pqrs/<uuid:pk>/', views.detalle_pqrs_admin, name='detalle_pqrs_admin'),
]