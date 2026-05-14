"""
decorators.py — Decoradores personalizados de control de acceso del módulo turnero.

Define el decorador @admin_requerido para restringir vistas al personal
administrativo autorizado (RBAC).
"""

from functools import wraps

from django.shortcuts import redirect
from django.contrib import messages


def admin_requerido(vista):
    """
    Decorador que restringe el acceso a una vista.

    Permite el acceso SOLO si el usuario cumple alguna de estas condiciones:
      1. Es superusuario (is_superuser=True).
      2. Es staff (is_staff=True) Y pertenece al grupo "Administrador".

    Cualquier otro usuario (Paciente, Operador, etc.) es redirigido
    a la página de inicio con un mensaje de error.
    """
    @wraps(vista)
    def _wrapper(request, *args, **kwargs):
        usuario = request.user

        # Verificar que el usuario esté autenticado
        if not usuario.is_authenticated:
            messages.error(request, 'Debes iniciar sesión para acceder.')
            return redirect('inicio')

        # Condición 1: superusuario tiene acceso total
        if usuario.is_superuser:
            return vista(request, *args, **kwargs)

        # Condición 2: staff + grupo "Administrador"
        if usuario.is_staff and usuario.groups.filter(name='Administrador').exists():
            return vista(request, *args, **kwargs)

        # Si no cumple ninguna condición → denegar acceso
        messages.error(
            request,
            'No tienes permisos para acceder al panel de administración.'
        )
        return redirect('home')

    return _wrapper


def operador_requerido(vista):
    """
    Decorador que restringe el acceso a vistas del panel de operador.

    Permite el acceso SOLO si el usuario cumple alguna de estas condiciones:
      1. Es superusuario (is_superuser=True).
      2. Es staff (is_staff=True) Y pertenece al grupo "Operador".
    """
    @wraps(vista)
    def _wrapper(request, *args, **kwargs):
        usuario = request.user

        if not usuario.is_authenticated:
            messages.error(request, 'Debes iniciar sesión para acceder.')
            return redirect('inicio')

        if usuario.is_superuser:
            return vista(request, *args, **kwargs)

        if usuario.is_staff and usuario.groups.filter(name='Operador').exists():
            return vista(request, *args, **kwargs)

        messages.error(
            request,
            'No tienes permisos para acceder al panel de operador.'
        )
        return redirect('home')

    return _wrapper
