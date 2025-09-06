from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from .serializers import RegisterSerializer

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = []
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        resp = super().create(request, *args, **kwargs)
        return Response(resp.data, status=status.HTTP_201_CREATED)
