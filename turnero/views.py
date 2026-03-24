from django.shortcuts import render

def inicio(request):
    return render(request, 'index.html')
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
        "nombre_usuario": "David Sánchez",
        "servicios": servicios
    }

    return render(request, 'home.html', contexto)

# Create your views here.
