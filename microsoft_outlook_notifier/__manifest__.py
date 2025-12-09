# -*- coding: utf-8 -*-
{
    "name": "Microsoft Outlook Token Notifier",
    "version": "1.0",
    "author": "Pedro Pereira Vaz",
    "website": "https://wavext.io",
    "category": "Productivity/Discuss",
    "summary": "Notificaciones automáticas antes de que expire el client secret de Outlook",
    "description": """
        Notificador de Token de Microsoft Outlook
        =========================================

        Monitorea tus integraciones con Microsoft Outlook y te avisa antes de que 
        dejen de funcionar.

        ¿Qué problema resuelve?
        -----------------------
        Los client secrets de Azure AD expiran. Cuando esto ocurre, Odoo deja de
        enviar y recibir emails sin previo aviso. Este módulo te notifica a tiempo
        para que puedas renovar el secret antes de que haya problemas.

        Características
        ---------------
        * Detecta automáticamente cuando un token falla
        * Aviso 30 días antes de la expiración (si configuras la fecha)
        * Notificaciones por email y por Discuss
        * Máximo 1 notificación por día (sin spam)

        Configuración
        -------------
        1. Ve a Ajustes → General → sección Outlook
        2. Establece "Secret Expires On" con la fecha de expiración de tu secret
        3. El módulo validará los tokens diariamente
    """,
    "depends": ["microsoft_outlook"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/res_config_settings_views.xml",
    ],
    "images": [],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
