import requests
import re


class EmailValidator:
    """邮箱验证服务，使用 Rapid Email Verifier API"""
    
    def __init__(self):
        self.base_url = "https://rapid-email-verifier.fly.dev/api/validate"
        self.timeout = 3  # 3秒超时
    
    def validate_email(self, email):
        """
        验证邮箱地址
        
        Args:
            email (str): 要验证的邮箱地址
            
        Returns:
            dict: 验证结果
                {
                    'valid': bool,  # 邮箱是否有效
                    'reason': str,  # 如果无效，说明原因
                    'details': dict  # 详细信息（可选）
                }
        """
        # 基本格式检查
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return {
                'valid': False,
                'reason': '邮箱格式不正确',
                'details': {}
            }
        
        # 调用 Rapid Email Verifier API
        try:
            params = {
                "email": email
            }
            
            response = requests.get(
                self.base_url,
                params=params,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_api_response(data)
            else:
                # API 调用失败，降级为基本验证
                return {
                    'valid': True,
                    'reason': f'API error (status {response.status_code}), basic validation passed',
                    'details': {'validation_type': 'basic_fallback'}
                }
                
        except requests.exceptions.Timeout:
            # 超时，降级为基本验证
            return {
                'valid': True,
                'reason': 'API timeout, basic validation passed',
                'details': {'validation_type': 'basic_fallback'}
            }
        except Exception as e:
            # 其他错误，降级为基本验证
            return {
                'valid': True,
                'reason': f'Validation error: {str(e)}, basic validation passed',
                'details': {'validation_type': 'basic_fallback'}
            }
    
    def _parse_api_response(self, data):
        """
        解析 API 响应
        
        Args:
            data (dict): API 返回的数据
            email (str): 邮箱地址
            
        Returns:
            dict: 标准化的验证结果
        """
        validations = data.get('validations', {})
        score = data.get('score', 0)
        status = data.get('status', 'UNKNOWN')
        typo_suggestion = data.get('typoSuggestion', '')
        
        # 检查语法
        if not validations.get('syntax', False):
            return {
                'valid': False,
                'reason': '邮箱格式不正确',
                'details': data
            }
        
        # 检查域名是否存在
        if not validations.get('domain_exists', False):
            reason = '邮箱域名不存在'
            if typo_suggestion:
                reason = f'邮箱域名不存在，您是否想输入：{typo_suggestion}？'
            return {
                'valid': False,
                'reason': reason,
                'details': data
            }
        
        # 检查 MX 记录
        if not validations.get('mx_records', False):
            reason = '邮箱域名无法接收邮件'
            if typo_suggestion:
                reason = f'邮箱域名无法接收邮件，您是否想输入：{typo_suggestion}？'
            return {
                'valid': False,
                'reason': reason,
                'details': data
            }
        
        # 检查是否为临时邮箱
        if validations.get('is_disposable', False):
            return {
                'valid': False,
                'reason': '不允许使用临时邮箱',
                'details': data
            }
        
        # 根据状态进行判断
        if status == 'INVALID':
            return {
                'valid': False,
                'reason': '邮箱地址无效',
                'details': data
            }
        
        if status == 'INVALID_DOMAIN':
            reason = '邮箱域名无效'
            if typo_suggestion:
                reason = f'邮箱域名无效，您是否想输入：{typo_suggestion}？'
            return {
                'valid': False,
                'reason': reason,
                'details': data
            }
        
        # 检查评分（降低阈值，因为 PROBABLY_VALID 状态的邮箱评分可能在 60-90 之间）
        if score < 60:
            reason = f'邮箱可信度过低（评分：{score}/100）'
            if typo_suggestion:
                reason = f'邮箱可信度过低（评分：{score}/100），建议使用：{typo_suggestion}'
            return {
                'valid': False,
                'reason': reason,
                'details': data
            }
        
        # VALID 或 PROBABLY_VALID 状态，且评分 >= 60，认为有效
        if status in ['VALID', 'PROBABLY_VALID']:
            reason = '邮箱验证通过'
            if typo_suggestion:
                reason = f'邮箱验证通过（但你可能想输入的是：{typo_suggestion}？）'
            return {
                'valid': True,
                'reason': reason,
                'details': data
            }
        
        # 检查邮箱是否存在（如果 API 提供此信息）
        # 注意：某些邮箱服务器不允许验证邮箱存在性，mailbox_exists 可能为 false
        # 但如果其他验证都通过，且评分足够高，仍然可以接受
        if 'mailbox_exists' in validations and not validations.get('mailbox_exists', True):
            # 如果评分足够高（>= 70），即使 mailbox_exists 为 false 也接受
            if score >= 70:
                return {
                    'valid': True,
                    'reason': '邮箱验证通过（无法验证邮箱存在性，但其他验证通过）',
                    'details': data
                }
            else:
                return {
                    'valid': False,
                    'reason': '无法验证邮箱地址是否存在',
                    'details': data
                }
        
        # 默认：如果评分 >= 60，认为有效
        if score >= 60:
            return {
                'valid': True,
                'reason': '邮箱验证通过',
                'details': data
            }
        
        # 评分过低
        return {
            'valid': False,
            'reason': f'邮箱可信度不足（评分：{score}/100）',
            'details': data
        }


# 创建全局实例
email_validator = EmailValidator()
