"""
Notification Service
Sends daily decision reports via Email (Resend API) and/or Webhook (Slack, Discord, Feishu, WeCom, generic).

Email is sent to all subscribed users (users.email_subscribed = True).
"""

import json
import traceback
from datetime import date
from typing import Optional, Dict, List

import resend
import requests


class NotificationService:
    """Handles sending notifications after daily pipeline runs."""

    def __init__(self, app_config: dict = None):
        self.config = app_config or {}
        # Configure Resend API key
        api_key = self.config.get('RESEND_API_KEY', '')
        if api_key:
            resend.api_key = api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_daily_result(self, decision_result: dict, pipeline_summary: dict) -> Dict:
        """
        Send notification after daily pipeline completes.
        Emails are sent to ALL subscribed users in the database.

        Args:
            decision_result: The decision log dict from TrackingService.run_daily_decision()
            pipeline_summary: Extra context (price_refresh, snapshot info, etc.)

        Returns:
            {'email_sent': bool, 'email_count': int, 'webhook_sent': bool, 'errors': [str]}
        """
        errors = []
        email_sent = False
        email_count = 0
        webhook_sent = False

        # Build message content
        subject = self._build_subject(decision_result)
        text_body = self._build_text_body(decision_result, pipeline_summary)
        html_body = self._build_html_body(decision_result, pipeline_summary)

        # Send email to all subscribers if Resend is configured
        resend_api_key = self.config.get('RESEND_API_KEY')
        if resend_api_key:
            try:
                recipients = self._get_subscribed_emails()
                if recipients:
                    sent, send_errors = self._send_batch_email(subject, html_body, recipients)
                    email_count = sent
                    email_sent = sent > 0
                    errors.extend(send_errors)
                    print(f"✅ [Notify] Email sent to {sent}/{len(recipients)} subscribers")
                else:
                    print("ℹ️  [Notify] No subscribed users found, skipping email")
            except Exception as e:
                err = f"Email failed: {e}"
                errors.append(err)
                print(f"❌ [Notify] {err}")
                traceback.print_exc()
        else:
            print("ℹ️  [Notify] Resend API key not configured, skipping email")

        # Send webhook if configured
        webhook_url = self.config.get('NOTIFY_WEBHOOK_URL')
        if webhook_url:
            try:
                self._send_webhook(webhook_url, decision_result, pipeline_summary)
                webhook_sent = True
                print(f"✅ [Notify] Webhook sent")
            except Exception as e:
                err = f"Webhook failed: {e}"
                errors.append(err)
                print(f"❌ [Notify] {err}")
                traceback.print_exc()

        if not resend_api_key and not webhook_url:
            print("ℹ️  [Notify] No notification channels configured (set RESEND_API_KEY or NOTIFY_WEBHOOK_URL)")

        return {
            'email_sent': email_sent,
            'email_count': email_count,
            'webhook_sent': webhook_sent,
            'errors': errors,
        }

    def send_test_email(self, to_email: str) -> Dict:
        """Send a single test email to verify Resend configuration."""
        resend_api_key = self.config.get('RESEND_API_KEY')
        if not resend_api_key:
            return {'success': False, 'error': 'RESEND_API_KEY not configured'}

        from_email = self.config.get('RESEND_FROM', 'InvestPilot <onboarding@resend.dev>')
        try:
            r = resend.Emails.send({
                "from": from_email,
                "to": [to_email],
                "subject": "📈 InvestPilot — Test Notification",
                "html": (
                    '<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    '<h1 style="color:#6366f1;">✅ InvestPilot Notification Test</h1>'
                    '<p>If you received this email, your notification setup is working correctly!</p>'
                    '<p style="color:#9ca3af;font-size:12px;margin-top:24px;">Sent by InvestPilot Notification Service · Powered by Resend</p>'
                    '</div>'
                ),
            })
            return {'success': True, 'resend_id': r.get('id', '') if isinstance(r, dict) else str(r)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def _get_subscribed_emails(self) -> List[str]:
        """Query all users with email_subscribed=True from the database."""
        try:
            from app.models.analysis import User
            subscribers = User.query.filter_by(email_subscribed=True).all()
            return [u.email for u in subscribers if u.email]
        except Exception as e:
            print(f"⚠️ [Notify] Failed to query subscribers: {e}")
            # Fallback: try the legacy NOTIFY_EMAIL config
            fallback = self.config.get('NOTIFY_EMAIL', '')
            return [fallback] if fallback else []

    # ------------------------------------------------------------------
    # Resend email sender (batch)
    # ------------------------------------------------------------------

    def _send_batch_email(self, subject: str, html_body: str, recipients: List[str]) -> tuple:
        """
        Send email to multiple recipients using Resend API.
        Sends individual emails to each recipient (not CC/BCC) for privacy.

        Returns:
            (sent_count, errors_list)
        """
        from_email = self.config.get('RESEND_FROM', 'InvestPilot <onboarding@resend.dev>')
        sent = 0
        errors = []

        # Resend supports batch sending via resend.Batch.send()
        params_list = [
            {
                "from": from_email,
                "to": [email],
                "subject": subject,
                "html": html_body,
            }
            for email in recipients
        ]

        try:
            # Use batch API for efficiency (sends all emails in one request)
            if len(params_list) == 1:
                # Single recipient — use simple send
                resend.Emails.send(params_list[0])
                sent = 1
            else:
                # Multiple recipients — use batch send
                resend.Batch.send(params_list)
                sent = len(params_list)
        except Exception as e:
            err_msg = f"Resend batch send failed: {e}"
            errors.append(err_msg)
            print(f"❌ [Notify] {err_msg}")
            # Fallback: try sending individually
            if len(params_list) > 1:
                print("ℹ️  [Notify] Falling back to individual sends...")
                for params in params_list:
                    try:
                        resend.Emails.send(params)
                        sent += 1
                    except Exception as ie:
                        errors.append(f"Failed to send to {params['to'][0]}: {ie}")

        return sent, errors

    # ------------------------------------------------------------------
    # Subject / Text body
    # ------------------------------------------------------------------

    def _build_subject(self, result: dict) -> str:
        today = result.get('date', date.today().strftime('%Y-%m-%d'))
        regime = result.get('market_regime', 'N/A')
        has_changes = result.get('has_changes', False)

        regime_emoji = {'RISK-ON': '🟢', 'NEUTRAL': '🟡', 'RISK-OFF': '🔴'}.get(regime, '⚪')
        action_text = "Portfolio Updated" if has_changes else "No Changes"

        return f"📈 InvestPilot Daily Report — {today} | {regime_emoji} {regime} | {action_text}"

    def _build_text_body(self, result: dict, summary: dict) -> str:
        """Plain-text fallback for email clients that don't support HTML."""
        lines = []
        today = result.get('date', 'N/A')
        regime = result.get('market_regime', 'N/A')
        confidence = result.get('confidence_level', 'N/A')

        lines.append(f"InvestPilot Daily Report — {today}")
        lines.append(f"Market Regime: {regime}")
        lines.append(f"Confidence: {confidence}")
        lines.append("")

        # Actions
        actions = result.get('actions', [])
        if actions:
            lines.append("Actions Taken:")
            for act in actions:
                action_type = act.get('action', '?')
                symbol = act.get('symbol', '?')
                reason = act.get('reason', '')[:120]
                lines.append(f"  {action_type} {symbol} — {reason}")
        else:
            lines.append("No portfolio changes today.")

        lines.append("")

        # Pipeline summary
        refresh = summary.get('price_refresh', {})
        snapshot = summary.get('snapshot', {})
        if refresh:
            lines.append(f"Price Refresh: {refresh.get('updated', 0)}/{refresh.get('total', 0)} stocks updated")
        if snapshot:
            pv = snapshot.get('portfolio_value', 'N/A')
            ret = snapshot.get('total_return_pct', 'N/A')
            lines.append(f"Portfolio Value: ${pv}  |  Total Return: {ret}%")

        # Holdings review scores
        report = result.get('report', {})
        if report and report.get('holdings_review'):
            lines.append("")
            lines.append("Holdings Score Card:")
            for h in report['holdings_review']:
                sym = h.get('symbol', '?')
                score = h.get('composite_score', 'N/A')
                rec = h.get('recommendation', 'N/A')
                lines.append(f"  {sym}: Score={score}, Rec={rec}")

        # AI Summary
        ai_summary = result.get('summary', '')
        if ai_summary:
            lines.append("")
            lines.append("AI Summary:")
            lines.append(ai_summary[:500])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTML email body
    # ------------------------------------------------------------------

    def _build_html_body(self, result: dict, summary: dict) -> str:
        today = result.get('date', 'N/A')
        regime = result.get('market_regime', 'N/A')
        confidence = result.get('confidence_level', 'N/A')
        actions = result.get('actions', [])
        report = result.get('report', {})

        regime_color = {'RISK-ON': '#22c55e', 'NEUTRAL': '#eab308', 'RISK-OFF': '#ef4444'}.get(regime, '#94a3b8')
        regime_emoji = {'RISK-ON': '🟢', 'NEUTRAL': '🟡', 'RISK-OFF': '🔴'}.get(regime, '⚪')

        # Actions HTML
        actions_html = ""
        if actions:
            action_rows = ""
            for act in actions:
                act_type = act.get('action', '?')
                symbol = act.get('symbol', '?')
                name = act.get('name', symbol)
                reason = act.get('reason', '')[:150]
                badge_color = '#22c55e' if act_type == 'BUY' else '#ef4444'
                action_rows += f"""
                <tr>
                    <td style="padding:8px 12px;"><span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">{act_type}</span></td>
                    <td style="padding:8px 12px;font-weight:bold;">{symbol}</td>
                    <td style="padding:8px 12px;color:#6b7280;">{name}</td>
                    <td style="padding:8px 12px;color:#374151;font-size:13px;">{reason}</td>
                </tr>"""
            actions_html = f"""
            <h2 style="color:#1f2937;margin:24px 0 12px;">📋 Actions</h2>
            <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;">
                <thead><tr style="background:#f9fafb;">
                    <th style="padding:8px 12px;text-align:left;font-size:13px;color:#6b7280;">Action</th>
                    <th style="padding:8px 12px;text-align:left;font-size:13px;color:#6b7280;">Symbol</th>
                    <th style="padding:8px 12px;text-align:left;font-size:13px;color:#6b7280;">Name</th>
                    <th style="padding:8px 12px;text-align:left;font-size:13px;color:#6b7280;">Reason</th>
                </tr></thead>
                <tbody>{action_rows}</tbody>
            </table>"""
        else:
            actions_html = '<p style="color:#6b7280;margin:16px 0;">✅ No portfolio changes today — all holdings are within acceptable parameters.</p>'

        # Holdings score card HTML
        holdings_html = ""
        if report and report.get('holdings_review'):
            h_rows = ""
            for h in report['holdings_review']:
                sym = h.get('symbol', '?')
                score = h.get('composite_score', 0)
                rec = h.get('recommendation', 'N/A')
                cat_score = h.get('catalyst_score', '-')
                tech_score = h.get('technical_score', '-')
                val_score = h.get('valuation_score', '-')
                # Star rating
                filled = int(round(score)) if isinstance(score, (int, float)) else 0
                stars = '★' * min(filled, 5) + '☆' * max(0, 5 - filled)
                score_color = '#22c55e' if score >= 4 else '#eab308' if score >= 2.5 else '#ef4444'
                h_rows += f"""
                <tr>
                    <td style="padding:6px 10px;font-weight:bold;">{sym}</td>
                    <td style="padding:6px 10px;text-align:center;">{cat_score}</td>
                    <td style="padding:6px 10px;text-align:center;">{tech_score}</td>
                    <td style="padding:6px 10px;text-align:center;">{val_score}</td>
                    <td style="padding:6px 10px;text-align:center;color:{score_color};font-weight:bold;">{score}</td>
                    <td style="padding:6px 10px;color:#d97706;">{stars}</td>
                    <td style="padding:6px 10px;">{rec}</td>
                </tr>"""
            holdings_html = f"""
            <h2 style="color:#1f2937;margin:24px 0 12px;">📊 Holdings Score Card</h2>
            <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;font-size:13px;">
                <thead><tr style="background:#f9fafb;">
                    <th style="padding:6px 10px;text-align:left;color:#6b7280;">Symbol</th>
                    <th style="padding:6px 10px;text-align:center;color:#6b7280;">Catalyst</th>
                    <th style="padding:6px 10px;text-align:center;color:#6b7280;">Technical</th>
                    <th style="padding:6px 10px;text-align:center;color:#6b7280;">Valuation</th>
                    <th style="padding:6px 10px;text-align:center;color:#6b7280;">Composite</th>
                    <th style="padding:6px 10px;text-align:center;color:#6b7280;">Rating</th>
                    <th style="padding:6px 10px;text-align:left;color:#6b7280;">Rec</th>
                </tr></thead>
                <tbody>{h_rows}</tbody>
            </table>"""

        # Portfolio snapshot
        snap = summary.get('snapshot', {})
        snap_html = ""
        if snap:
            pv = snap.get('portfolio_value', 'N/A')
            ret = snap.get('total_return_pct', 'N/A')
            cash = snap.get('cash', 'N/A')
            snap_html = f"""
            <div style="display:flex;gap:16px;margin:16px 0;">
                <div style="flex:1;background:#f0fdf4;padding:12px 16px;border-radius:8px;text-align:center;">
                    <div style="font-size:12px;color:#6b7280;">Portfolio Value</div>
                    <div style="font-size:20px;font-weight:bold;color:#1f2937;">${pv}</div>
                </div>
                <div style="flex:1;background:#eff6ff;padding:12px 16px;border-radius:8px;text-align:center;">
                    <div style="font-size:12px;color:#6b7280;">Total Return</div>
                    <div style="font-size:20px;font-weight:bold;color:#2563eb;">{ret}%</div>
                </div>
                <div style="flex:1;background:#fefce8;padding:12px 16px;border-radius:8px;text-align:center;">
                    <div style="font-size:12px;color:#6b7280;">Cash</div>
                    <div style="font-size:20px;font-weight:bold;color:#ca8a04;">${cash}</div>
                </div>
            </div>"""

        # AI summary
        ai_summary = result.get('summary', '')
        summary_html = ""
        if ai_summary:
            summary_html = f"""
            <h2 style="color:#1f2937;margin:24px 0 12px;">💬 AI Summary</h2>
            <div style="background:#f9fafb;padding:16px;border-radius:8px;border-left:4px solid #6366f1;color:#374151;line-height:1.6;font-size:14px;">
                {ai_summary[:800]}
            </div>"""

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#1f2937;">
    <div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:24px;border-radius:12px 12px 0 0;color:#fff;">
        <h1 style="margin:0;font-size:22px;">📈 InvestPilot Daily Report</h1>
        <p style="margin:8px 0 0;opacity:0.9;font-size:14px;">{today}</p>
    </div>

    <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 12px 12px;">
        <div style="display:flex;gap:12px;margin-bottom:20px;">
            <div style="background:{regime_color}22;border:1px solid {regime_color};padding:8px 16px;border-radius:8px;">
                <span style="font-size:13px;color:#6b7280;">Market Regime</span><br>
                <strong style="color:{regime_color};font-size:16px;">{regime_emoji} {regime}</strong>
            </div>
            <div style="background:#f3f4f6;border:1px solid #e5e7eb;padding:8px 16px;border-radius:8px;">
                <span style="font-size:13px;color:#6b7280;">Confidence</span><br>
                <strong style="color:#374151;font-size:16px;">{confidence}</strong>
            </div>
        </div>

        {snap_html}
        {actions_html}
        {holdings_html}
        {summary_html}

        <hr style="border:0;border-top:1px solid #e5e7eb;margin:24px 0 12px;">
        <p style="color:#9ca3af;font-size:12px;text-align:center;">
            Sent by InvestPilot Notification Service · Powered by Resend
        </p>
    </div>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Webhook sender (auto-detects platform)
    # ------------------------------------------------------------------

    def _send_webhook(self, url: str, result: dict, summary: dict):
        """
        Send notification to a webhook URL.
        Auto-detects: Slack, Discord, Feishu (Lark), WeCom (WeChat Work), or generic POST.
        """
        today = result.get('date', 'N/A')
        regime = result.get('market_regime', 'N/A')
        has_changes = result.get('has_changes', False)
        actions = result.get('actions', [])
        ai_summary = result.get('summary', '')[:300]

        snap = summary.get('snapshot', {})
        pv = snap.get('portfolio_value', 'N/A')
        ret = snap.get('total_return_pct', 'N/A')

        regime_emoji = {'RISK-ON': '🟢', 'NEUTRAL': '🟡', 'RISK-OFF': '🔴'}.get(regime, '⚪')

        # Build actions text
        action_lines = []
        for act in actions:
            act_type = act.get('action', '?')
            symbol = act.get('symbol', '?')
            emoji = '🟢' if act_type == 'BUY' else '🔴'
            action_lines.append(f"{emoji} {act_type} {symbol}")
        actions_text = "\n".join(action_lines) if action_lines else "No changes"

        text = (
            f"📈 InvestPilot Daily Report — {today}\n"
            f"Market: {regime_emoji} {regime}\n"
            f"Portfolio: ${pv} | Return: {ret}%\n\n"
            f"{actions_text}\n\n"
            f"{ai_summary}"
        )

        # Auto-detect platform from URL
        url_lower = url.lower()

        if 'hooks.slack.com' in url_lower:
            payload = {"text": text}
        elif 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            payload = {"content": text[:2000]}
        elif 'open.feishu.cn' in url_lower or 'open.larksuite.com' in url_lower:
            payload = {
                "msg_type": "text",
                "content": {"text": text}
            }
        elif 'qyapi.weixin.qq.com' in url_lower:
            payload = {
                "msgtype": "text",
                "text": {"content": text}
            }
        else:
            payload = {
                "text": text,
                "date": today,
                "market_regime": regime,
                "has_changes": has_changes,
                "actions": actions,
                "portfolio_value": pv,
                "total_return_pct": ret,
            }

        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()


# Singleton (lazily initialized with app config)
_notification_service: Optional[NotificationService] = None


def get_notification_service(app_config: dict = None) -> NotificationService:
    """Get or create the singleton NotificationService."""
    global _notification_service
    if _notification_service is None or app_config is not None:
        _notification_service = NotificationService(app_config or {})
    return _notification_service
