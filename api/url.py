from django.urls import path

from . import views

urlpatterns = [
    path('user/verify_code/', views.VerifyCodeInterface.get_view(), name='verify_code'),
    path('user/login/', views.LoginInterface.get_view(), name='login'),
    path('user/register/', views.RegisterInterface.get_view(), name='register'),
    path('user/username_available/', views.UsernameAvailableInterface.get_view(), name='usernamea_available'),
    path('user/refresh_token/', views.RefreshAccessTokenInterface.get_view(), name="refresh_token"),
    path('test/verify_code/', views.VerifyCodeTestInterface.get_view(), name='verify_code_test'),
    path('test/token/', views.AccessTokenTestInterface.get_view(), name="token_test"),
]