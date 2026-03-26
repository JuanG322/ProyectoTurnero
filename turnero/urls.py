from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),                 
    path('register/', views.registro, name='registro'),    
    path('home/', views.home, name='home'),                
]