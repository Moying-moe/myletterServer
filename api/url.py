from django.urls import path

from . import views

urlpatterns = [
    path('user/verify_code/', views.VerifyCodeInterface.get_view(), name='verify_code'),
    path('user/login/', views.LoginInterface.get_view(), name='login'),
    path('test/verify_code/', views.VerifyCodeTestInterface.get_view(), name='verify_code_test'),
]