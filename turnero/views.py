from django.shortcuts import render, redirect

def inicio(request):
    return render(request, 'Login.html')

def registro(request):
    if request.method == 'POST':
        return redirect('home')
    
    return render(request, 'Register.html')

def home(request):
    servicios = [
        {"nombre": "Laboratorio", "tiempo_estimado": "Pendiente"},
        {"nombre": "Pagos", "tiempo_estimado": "Pendiente"},
        {"nombre": "Citas", "tiempo_estimado": "Pendiente"},
        {"nombre": "Atención al cliente", "tiempo_estimado": "Pendiente"},
        {"nombre": "Farmacia", "tiempo_estimado": "Pendiente"},
        {"nombre": "Vacunación", "tiempo_estimado": "Pendiente"},
    ]

    contexto = {
        "nombre_usuario": "Nuevo Usuario", # Temporalmente ponemos un nombre genérico
        "servicios": servicios
    }

    return render(request, 'home.html', contexto)