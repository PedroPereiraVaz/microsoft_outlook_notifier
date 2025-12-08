# -*- coding: utf-8 -*-
import logging
from datetime import date

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

NOTIFY_DAYS_BEFORE = 30


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    microsoft_outlook_secret_expiration = fields.Date(
        string='Outlook Secret Expiration Date',
        help='Expiration date of your Azure AD client secret.'
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo().get_param(
            'microsoft_outlook_secret_expiration', ''
        )
        if param:
            try:
                res['microsoft_outlook_secret_expiration'] = fields.Date.from_string(param)
            except (ValueError, TypeError):
                pass
        return res

    def set_values(self):
        super().set_values()
        value = ''
        if self.microsoft_outlook_secret_expiration:
            value = fields.Date.to_string(self.microsoft_outlook_secret_expiration)
        self.env['ir.config_parameter'].sudo().set_param(
            'microsoft_outlook_secret_expiration', value
        )


class OutlookSecretNotifier(models.AbstractModel):
    _name = 'outlook.secret.notifier'
    _description = 'Microsoft Outlook Secret Notifier'

    @api.model
    def _cron_check_outlook_tokens(self):
        """Daily cron: check expiration date AND validate active Outlook server tokens."""
        Config = self.env['ir.config_parameter'].sudo()
        today = date.today()
        today_str = today.strftime('%Y-%m-%d')
        
        # Check if already notified today
        last_notif = Config.get_param('outlook_notifier_last_date', '')
        if last_notif == today_str:
            _logger.debug('Outlook notification already sent today.')
            return
        
        notifications = []
        
        # 1. Check manual expiration date
        exp_str = Config.get_param('microsoft_outlook_secret_expiration', '')
        if exp_str:
            try:
                exp_date = fields.Date.from_string(exp_str)
                days_left = (exp_date - today).days
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
        
        # 2. Validate tokens on active Outlook servers
        token_errors = self._check_outlook_servers()
        notifications.extend(token_errors)
        
        if notifications:
            self._send_notifications(notifications)
            Config.set_param('outlook_notifier_last_date', today_str)

    def _check_outlook_servers(self):
        """Try to validate tokens on all active Outlook servers."""
        errors = []
        
        # Check outgoing mail servers
        mail_servers = self.env['ir.mail_server'].sudo().search([
            ('smtp_authentication', '=', 'outlook'),
        ])
        for server in mail_servers:
            if not server.microsoft_outlook_refresh_token:
                continue
            try:
                server._generate_outlook_oauth2_string(server.smtp_user)
            except Exception as e:
                errors.append(_('❌ Servidor saliente "%s": %s') % (server.name, str(e)[:100]))
        
        # Check incoming mail servers (fetchmail)
        try:
            fetchmail_servers = self.env['fetchmail.server'].sudo().search([
                ('server_type', '=', 'outlook'),
                ('state', '=', 'done'),
            ])
            for server in fetchmail_servers:
                if not server.microsoft_outlook_refresh_token:
                    continue
                try:
                    server._generate_outlook_oauth2_string(server.user)
                except Exception as e:
                    errors.append(_('❌ Servidor entrante "%s": %s') % (server.name, str(e)[:100]))
        except Exception:
            pass  # fetchmail module might not be installed
        
        return errors

    def _send_notifications(self, messages):
        """Send notifications via channel and email."""
        body = Markup('<b>🔔 Alerta Microsoft Outlook</b><br/><br/>') + Markup('<br/>').join(messages)
        body += Markup(_('''<br/><br/><b>Pasos para solucionar:</b>
1. Ir a Azure Portal → App registrations → Tu App → Certificates & secrets
2. Crear un nuevo client secret (si expiró)
3. Actualizar el secret en Odoo → Settings → Outlook
4. Volver a autorizar los servidores de correo'''))
        
        # Post to admin channel
        channel = self.env.ref('mail.channel_admin', raise_if_not_found=False)
        if channel:
            try:
                channel.sudo().message_post(body=body, message_type='notification')
            except Exception as e:
                _logger.error('Failed to post to admin channel: %s', e)
        
        # Email to admin users
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
                _logger.error('Failed to send email to %s: %s', user.email, e)
        
        _logger.info('Outlook notification sent with %d alerts.', len(messages))
