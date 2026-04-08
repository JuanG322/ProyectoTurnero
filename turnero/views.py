from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from .models import Usuario

def inicio(request):
    # Si el usuario ya inició sesión, no tiene sentido que vea el login, lo mandamos al home
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        tipo_doc = request.POST.get('tipo_doc')
        num_doc = request.POST.get('num_doc')
        password = request.POST.get('password')

        try:
            # Buscamos al usuario en la base de datos por su documento
            usuario = Usuario.objects.get(tipo_documento=tipo_doc, num_documento=num_doc)
            
            # Verificamos si la contraseña coincide
            if usuario.check_password(password):
                # Como no estamos usando el sistema de login por defecto (que usa email), 
                # forzamos el backend de autenticación y hacemos el login manualmente.
                usuario.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, usuario)
                return redirect('home')
            else:
                messages.error(request, 'Contraseña incorrecta.')
        except Usuario.DoesNotExist:
            messages.error(request, 'No existe un usuario con este documento.')

    return render(request, 'Login.html')

def registro(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        nombre = request.POST.get('nombre_completo')
        tipo_doc = request.POST.get('tipo_doc')
        num_doc = request.POST.get('identificacion')
        email = request.POST.get('correo')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')

        # Validaciones extra en el backend (por si alguien salta las de JavaScript)
        if password != password_confirm:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(request, 'Register.html')
        
        if Usuario.objects.filter(num_documento=num_doc).exists():
            messages.error(request, 'Ya existe una cuenta con este número de documento.')
            return render(request, 'Register.html')
            
        if Usuario.objects.filter(email=email).exists():
            messages.error(request, 'Este correo electrónico ya está registrado.')
            return render(request, 'Register.html')

        # Crear el usuario de forma segura
        usuario = Usuario.objects.create_user(
            identificacion=num_doc,
            email=email,
            nombre_completo=nombre,
            password=password,
            tipo_documento=tipo_doc
        )
        
        # Opcional: Iniciar sesión automáticamente tras un registro exitoso
        usuario.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, usuario)
        
        return redirect('home')
    
    return render(request, 'Register.html')

def home(request):
    # Si alguien intenta entrar a /home sin iniciar sesión, lo devolvemos al login
    if not request.user.is_authenticated:
        return redirect('inicio')

    servicios = [
        {"nombre": "Laboratorio", "tiempo_estimado": "Pendiente"},
        {"nombre": "Pagos", "tiempo_estimado": "Pendiente"},
        {"nombre": "Citas", "tiempo_estimado": "Pendiente"},
        {"nombre": "Atención al cliente", "tiempo_estimado": "Pendiente"},
        {"nombre": "Farmacia", "tiempo_estimado": "Pendiente"},
        {"nombre": "Vacunación", "tiempo_estimado": "Pendiente"},
    ]

    contexto = {
        # Ahora inyectamos el nombre real del usuario logueado en la base de datos
        "nombre_usuario": request.user.nombre, 
        "servicios": servicios
    }

    return render(request, 'home.html', contexto)

def salir(request):
    logout(request)
    return redirect('inicio')