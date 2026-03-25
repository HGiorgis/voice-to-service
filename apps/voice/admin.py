from django.contrib import admin
from .models import VoiceProcessingRequest


@admin.register(VoiceProcessingRequest)
class VoiceProcessingRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'category', 'confidence', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('amharic_text', 'english_text', 'user__email', 'user__username')
    readonly_fields = ('id', 'created_at', 'pipeline_metadata')
    raw_id_fields = ('user',)
