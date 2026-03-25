from django.urls import path
from .views.voice_views import ProcessAudioView

urlpatterns = [
    path('process-audio/', ProcessAudioView.as_view(), name='process-audio'),
]
