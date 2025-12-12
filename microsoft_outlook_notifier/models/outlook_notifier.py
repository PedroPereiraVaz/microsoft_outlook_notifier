# -*- coding: utf-8 -*-
import logging
from datetime import date

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Cantidad de días previos a la expiración para comenzar a notificar
NOTIFY_DAYS_BEFORE = 30


class ResConfigSettings(models.TransientModel):
    # Heredamos de res.config.settings para añadir la configuración de expiración
    _inherit = 'res.config.settings'

    microsoft_outlook_secret_expiration = fields.Date(
        string='Outlook Secret Expiration Date',
        help='Expiration date of your Azure AD client secret.'
    )

    @api.model
    def get_values(self):
        # Obtiene los valores guardados en la configuración del sistema
        res = super().get_values()
        # Recuperamos el parámetro del sistema
        param = self.env['ir.config_parameter'].sudo().get_param(
            'microsoft_outlook_secret_expiration', ''
        )
        if param:
            try:
                # Convertimos el string a fecha
                res['microsoft_outlook_secret_expiration'] = fields.Date.from_string(param)
            except (ValueError, TypeError):
                pass
        return res

    def set_values(self):
        # Guarda los valores en la configuración del sistema
        super().set_values()
        value = ''
        if self.microsoft_outlook_secret_expiration:
            # Convertimos la fecha a string para guardarla
            value = fields.Date.to_string(self.microsoft_outlook_secret_expiration)
        # Guardamos el parámetro en el sistema
        self.env['ir.config_parameter'].sudo().set_param(
            'microsoft_outlook_secret_expiration', value
        )


class OutlookSecretNotifier(models.AbstractModel):
    # Modelo abstracto (no crea tabla en BDD) para la lógica de notificación
    _name = 'outlook.secret.notifier'
    _description = 'Microsoft Outlook Secret Notifier'

    @api.model
    def _cron_check_outlook_tokens(self):
        """Cron diario: verifica la fecha de expiración Y valida los tokens de servidores Outlook activos."""
        Config = self.env['ir.config_parameter'].sudo()
        today = date.today()
        today_str = today.strftime('%Y-%m-%d')
        
        # Verificar si ya se envió la notificación hoy para no repetir
        last_notif = Config.get_param('outlook_notifier_last_date', '')
        if last_notif == today_str:
            _logger.debug('La notificación de Outlook ya se envió hoy.')
            return
        
        notifications = []
        
        # 1. Verificar la fecha de expiración manual configurada
        exp_str = Config.get_param('microsoft_outlook_secret_expiration', '')
        if exp_str:
            try:
                exp_date = fields.Date.from_string(exp_str)
                days_left = (exp_date - today).days
                
                # Si estamos dentro del periodo de notificación (30 días por defecto)
                if days_left <= NOTIFY_DAYS_BEFORE:
                    if days_left < 0:
                        notifications.append(_(
                            '⚠️ El client secret de Outlook EXPIRÓ hace %d días.'
                        ) % abs(days_left))
                    elif days_left == 0:
                        notifications.append(_('⚠️ El client secret de Outlook expira HOY.'))
                    else:
                        notifications.append(_(
                            '🔔 El client secret de Outlook expira en %d días (%s).'
                        ) % (days_left, exp_date.strftime('%d/%m/%Y')))
            except (ValueError, TypeError):
                pass
        
        # 2. Validar tokens de autenticación en servidores de correo activos
        token_errors = self._check_outlook_servers()
        notifications.extend(token_errors)
        
        # Si existe alguna notificación o error, enviamos el aviso
        if notifications:
            self._send_notifications(notifications)
            # Guardamos la fecha de hoy para no volver a enviar hasta mañana
            Config.set_param('outlook_notifier_last_date', today_str)

    def _check_outlook_servers(self):
        """Intenta validar los tokens en todos los servidores Outlook activos."""
        errors = []
        
        # Verificar servidores de correo saliente (SMTP)
        mail_servers = self.env['ir.mail_server'].sudo().search([
            ('smtp_authentication', '=', 'outlook'),
        ])
        for server in mail_servers:
            # Solo verificamos si tiene un token de refresco de Outlook
            if not server.microsoft_outlook_refresh_token:
                continue
            try:
                # Intentamos generar el string OAuth2; si falla, el token es inválido
                server._generate_outlook_oauth2_string(server.smtp_user)
            except Exception as e:
                errors.append(_('❌ Servidor saliente "%s": %s') % (server.name, str(e)[:100]))
        
        # Verificar servidores de correo entrante (Fetchmail)
        try:
            fetchmail_servers = self.env['fetchmail.server'].sudo().search([
                ('server_type', '=', 'outlook'),
                ('state', '=', 'done'), # Solo servidores confirmados/activos
            ])
            for server in fetchmail_servers:
                if not server.microsoft_outlook_refresh_token:
                    continue
                try:
                    server._generate_outlook_oauth2_string(server.user)
                except Exception as e:
                    errors.append(_('❌ Servidor entrante "%s": %s') % (server.name, str(e)[:100]))
        except Exception:
            # Ignoramos si el módulo fetchmail no está instalado
            pass
        
        return errors

    def _send_notifications(self, messages):
        """Envía notificaciones a través del canal de administración y correo electrónico."""
        # Construimos el cuerpo del mensaje combinando todas las alertas
        body = Markup('<b>🔔 Alerta Microsoft Outlook</b><br/><br/>') + Markup('<br/>').join(messages)
        body += Markup(_('''<br/><br/><b>Pasos para solucionar:</b>
1. Ir a Azure Portal → App registrations → Tu App → Certificates & secrets
2. Crear un nuevo client secret (si expiró)
3. Actualizar el secret en Odoo → Settings → Outlook
4. Volver a autorizar los servidores de correo'''))
        
        # Publicar en el canal de administración (generalmente #System o #General)
        channel = self.env.ref('mail.channel_admin', raise_if_not_found=False)
        if channel:
            try:
                channel.sudo().message_post(body=body, message_type='notification')
            except Exception as e:
                _logger.error('Error al publicar en el canal admin: %s', e)
        
        # Enviar correo electrónico a usuarios del grupo Administración/Ajustes
        admin_users = self.env['res.users'].sudo().search([
            ('groups_id', 'in', self.env.ref('base.group_system').id),
            ('email', '!=', False),
        ])
        email_from = self.env.company.email or 'noreply@localhost'
        for user in admin_users:
            try:
                self.env['mail.mail'].sudo().create({
                    'subject': _('🔔 Alerta Microsoft Outlook'),
                    'body_html': f'<p>{body}</p>',
                    'email_to': user.email,
                    'email_from': email_from,
                    'auto_delete': True,
                }).send()
            except Exception as e:
                _logger.error('Error al enviar correo a %s: %s', user.email, e)
        
        _logger.info('Notificación de Outlook enviada con %d alertas.', len(messages))
