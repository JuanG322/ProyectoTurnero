from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('home/', views.home, name='home'),
]