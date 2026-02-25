"""
Git SSH服务 - 生成SSH密钥并使用SSH方式访问Git仓库
"""

import os
import sys
import re
import shlex
import logging
import tempfile
import subprocess
import shutil
import hashlib
import base64
from typing import Tuple, Optional, Dict, List
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.backends import default_backend

# 配置日志
logger = logging.getLogger(__name__)


def is_valid_branch_name(branch: str) -> bool:
    """
    验证 Git 分支名是否合法

    Git 分支名规则:
    - 不能以 . 或 - 开头
    - 不能包含 .., ~, ^, :, ?, *, [, \\, 空格
    - 不能以 / 结尾
    - 不能以 .lock 结尾

    Args:
        branch: 分支名

    Returns:
        是否为合法的分支名
    """
    if not branch:
        return False

    # 基本格式检查：只允许字母、数字、-、_、/、.
    if not re.match(r'^[\w\-/.]+$', branch):
        return False

    # 不能以 . 或 - 开头
    if branch.startswith('.') or branch.startswith('-'):
        return False

    # 不能以 / 结尾
    if branch.endswith('/'):
        return False

    # 不能以 .lock 结尾
    if branch.endswith('.lock'):
        return False

    # 不能包含连续的 ..
    if '..' in branch:
        return False

    # 不能包含连续的 //
    if '//' in branch:
        return False

    return True


def get_ssh_config_dir() -> str:
    """
    获取SSH配置目录路径，如果不存在则创建

    Returns:
        SSH配置目录的绝对路径
    """
    from app.core.config import settings

    ssh_config_path = Path(settings.SSH_CONFIG_PATH)

    # 确保目录存在
    ssh_config_path.mkdir(parents=True, exist_ok=True)

    # 设置目录权限（仅所有者可访问）
    if sys.platform != 'win32':
        os.chmod(ssh_config_path, 0o700)

    return str(ssh_config_path.absolute())


def get_known_hosts_file() -> str:
    """
    获取known_hosts文件路径，如果不存在则创建

    Returns:
        known_hosts文件的绝对路径
    """
    ssh_config_dir = get_ssh_config_dir()
    known_hosts_file = Path(ssh_config_dir) / 'known_hosts'

    # 如果文件不存在则创建
    if not known_hosts_file.exists():
        known_hosts_file.touch()
        # 设置文件权限
        if sys.platform != 'win32':
            os.chmod(known_hosts_file, 0o600)

    return str(known_hosts_file.absolute())


def clear_known_hosts() -> bool:
    """
    清理known_hosts文件内容

    Returns:
        是否清理成功
    """
    try:
        known_hosts_file = get_known_hosts_file()
        # 清空文件内容
        with open(known_hosts_file, 'w') as f:
            f.write('')
        logger.info(f"Cleared known_hosts file: {known_hosts_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to clear known_hosts: {e}")
        return False


def set_secure_file_permissions(file_path: str):
    """
    设置文件的安全权限（Unix: 0600, Windows: 只有当前用户可读写）

    Args:
        file_path: 文件路径
    """
    if sys.platform == 'win32':
        # Windows系统使用icacls命令设置权限
        try:
            # 移除所有继承的权限
            subprocess.run(
                ['icacls', file_path, '/inheritance:r'],
                capture_output=True,
                check=True
            )
            # 只给当前用户完全控制权限
            subprocess.run(
                ['icacls', file_path, '/grant:r', f'{os.environ.get("USERNAME")}:(F)'],
                capture_output=True,
                check=True
            )
        except Exception as e:
            logger.warning(f"Failed to set Windows file permissions: {e}")
            # 尝试使用os.chmod作为后备方案
            try:
                os.chmod(file_path, 0o600)
            except Exception:
                pass
    else:
        # Unix/Linux/Mac系统
        os.chmod(file_path, 0o600)


class SSHKeyService:
    """SSH密钥服务"""

    @staticmethod
    def get_public_key_fingerprint(public_key: str) -> Optional[str]:
        """
        计算SSH公钥的SHA256指纹

        Args:
            public_key: SSH公钥（OpenSSH格式）

        Returns:
            SHA256指纹字符串，格式如: SHA256:Js1ypfoB+N2IfrCGgSj81vHnK4F/XxUV6Y9KUwKoFx8
        """
        try:
            # 解析公钥 (格式: ssh-ed25519 AAAAC3Nza...)
            parts = public_key.strip().split()
            if len(parts) < 2:
                return None

            # 获取base64编码的公钥数据
            key_data = parts[1]

            # 解码base64
            key_bytes = base64.b64decode(key_data)

            # 计算SHA256哈希
            sha256_hash = hashlib.sha256(key_bytes).digest()

            # 转换为base64（无填充）
            fingerprint = base64.b64encode(sha256_hash).decode('utf-8').rstrip('=')

            return f"SHA256:{fingerprint}"

        except Exception as e:
            logger.error(f"Fingerprint calculation error: {e}")
            return None

    @staticmethod
    def verify_key_pair(private_key: str, public_key: str) -> bool:
        """
        验证私钥和公钥是否匹配

        Args:
            private_key: SSH私钥（支持传统RSA PEM格式或OpenSSH格式）
            public_key: SSH公钥（OpenSSH格式）

        Returns:
            是否匹配
        """
        try:
            from cryptography.hazmat.primitives.serialization import (
                load_ssh_private_key,
                load_pem_private_key
            )
            from cryptography.hazmat.backends import default_backend

            # 尝试加载私钥（支持多种格式）
            private_key_bytes = private_key.encode('utf-8')
            private_key_obj = None

            # 首先尝试作为OpenSSH格式加载
            try:
                private_key_obj = load_ssh_private_key(
                    private_key_bytes,
                    password=None,
                    backend=default_backend()
                )
            except Exception:
                # 如果失败，尝试作为传统PEM格式加载（支持RSA、DSA、EC等）
                try:
                    private_key_obj = load_pem_private_key(
                        private_key_bytes,
                        password=None,
                        backend=default_backend()
                    )
                except Exception as e:
                    logger.debug(f"Failed to load private key: {e}")
                    return False

            if not private_key_obj:
                return False

            # 从私钥导出公钥
            derived_public_key = private_key_obj.public_key()
            derived_public_bytes = derived_public_key.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH
            ).decode('utf-8').strip()

            # 比较（去除可能的注释部分）
            expected_public = public_key.split()[0] + ' ' + public_key.split()[1]
            actual_public = derived_public_bytes.split()[0] + ' ' + derived_public_bytes.split()[1]

            return expected_public == actual_public

        except Exception as e:
            logger.error(f"Key verification error: {e}")
            return False

    @staticmethod
    def generate_rsa_key(key_size: int = 4096) -> Tuple[str, str]:
        """
        生成RSA SSH密钥对

        Args:
            key_size: RSA密钥大小（比特），默认4096

        Returns:
            (private_key, public_key): 私钥和公钥的元组，私钥使用传统PEM格式
        """
        # 生成RSA私钥
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )

        # 序列化私钥为传统PEM格式（BEGIN RSA PRIVATE KEY，兼容性更好）
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        # 获取公钥并序列化为OpenSSH格式
        public_key = private_key.public_key()
        public_openssh = public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        ).decode('utf-8')

        return private_pem, public_openssh

    @staticmethod
    def generate_ed25519_key() -> Tuple[str, str]:
        """
        生成ED25519 SSH密钥对（备用方法，默认使用RSA）

        Returns:
            (private_key, public_key): 私钥和公钥的元组，都是OpenSSH格式
        """
        # 生成ED25519私钥
        private_key = ed25519.Ed25519PrivateKey.generate()

        # 序列化私钥为OpenSSH格式
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        # 获取公钥并序列化为OpenSSH格式
        public_key = private_key.public_key()
        public_openssh = public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        ).decode('utf-8')

        return private_pem, public_openssh


class GitSSHOperations:
    """Git SSH操作类 - 使用SSH密钥克隆和拉取仓库"""

    @staticmethod
    def is_ssh_url(url: str) -> bool:
        """
        判断URL是否为SSH格式

        Args:
            url: Git仓库URL

        Returns:
            是否为SSH URL
        """
        return url.startswith('git@') or url.startswith('ssh://')

    @staticmethod
    def clone_repo_with_ssh(repo_url: str, private_key: str, target_dir: str, branch: str = None) -> Dict[str, any]:
        """
        使用SSH密钥克隆Git仓库

        Args:
            repo_url: SSH格式的Git URL (例如: git@github.com:user/repo.git)
            private_key: SSH私钥内容
            target_dir: 目标目录
            branch: 分支名称

        Returns:
            操作结果字典
        """
        from app.core.config import settings

        temp_dir = None
        try:
            # 验证分支名（如果提供）
            if branch and not is_valid_branch_name(branch):
                logger.warning(f"Invalid branch name rejected: {branch}")
                return {'success': False, 'message': f'无效的分支名: {branch}'}

            # 创建临时目录存放SSH密钥
            temp_dir = tempfile.mkdtemp(prefix='deepaudit_ssh_')
            key_file = os.path.join(temp_dir, 'id_rsa')

            # 写入私钥
            with open(key_file, 'w') as f:
                f.write(private_key)
            set_secure_file_permissions(key_file)

            # 使用持久化的known_hosts文件
            known_hosts_file = get_known_hosts_file()

            # 设置Git SSH命令，只使用DeepAudit生成的SSH密钥
            env = os.environ.copy()

            # 构建SSH命令（使用 shlex.quote 转义路径防止命令注入）
            ssh_cmd = (
                f"ssh -i {shlex.quote(key_file)} "
                f"-o StrictHostKeyChecking=accept-new "
                f"-o UserKnownHostsFile={shlex.quote(known_hosts_file)} "
                f"-o PreferredAuthentications=publickey "
                f"-o IdentitiesOnly=yes"
            )

            env['GIT_SSH_COMMAND'] = ssh_cmd
            logger.debug(f"Using SSH key file: {key_file}")
            logger.debug(f"Using known_hosts file: {known_hosts_file}")

            # 执行git clone
            cmd = ['git', 'clone', '--depth', '1']
            if branch:  # 只有明确指定分支时才添加
                cmd.extend(['--branch', branch])
            cmd.extend([repo_url, target_dir])

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=settings.SSH_CLONE_TIMEOUT
            )

            if result.returncode == 0:
                return {
                    'success': True,
                    'message': '仓库克隆成功',
                    'path': target_dir
                }
            else:
                logger.error(f"Git clone failed: {result.stderr}")
                return {
                    'success': False,
                    'message': '仓库克隆失败',
                    'error': result.stderr
                }

        except subprocess.TimeoutExpired:
            logger.error(f"Git clone timeout after {settings.SSH_CLONE_TIMEOUT}s")
            return {'success': False, 'message': f'克隆超时（超过{settings.SSH_CLONE_TIMEOUT}秒）'}
        except Exception as e:
            logger.error(f"Git clone error: {e}")
            return {'success': False, 'message': f'克隆失败: {str(e)}'}
        finally:
            # 清理临时文件
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def get_repo_files_via_ssh(repo_url: str, private_key: str, branch: str = "main",
                                exclude_patterns: List[str] = None) -> List[Dict[str, str]]:
        """
        通过SSH克隆仓库并获取文件列表

        Args:
            repo_url: SSH格式的Git URL
            private_key: SSH私钥
            branch: 分支名称
            exclude_patterns: 排除模式列表

        Returns:
            文件列表，每个文件包含path和内容
        """
        temp_clone_dir = None
        try:
            # 创建临时克隆目录
            temp_clone_dir = tempfile.mkdtemp(prefix='deepaudit_clone_')

            # 克隆仓库
            clone_result = GitSSHOperations.clone_repo_with_ssh(
                repo_url, private_key, temp_clone_dir, branch
            )

            if not clone_result['success']:
                raise Exception(f"克隆仓库失败: {clone_result.get('error', '')}")

            # 扫描目录获取文件列表
            from app.services.scanner import is_text_file, should_exclude

            files = []
            for root, dirs, filenames in os.walk(temp_clone_dir):
                # 排除.git目录
                if '.git' in dirs:
                    dirs.remove('.git')

                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    # 获取相对路径
                    rel_path = os.path.relpath(file_path, temp_clone_dir)

                    # 检查是否应该排除
                    if should_exclude(rel_path, exclude_patterns):
                        continue

                    # 只处理文本文件
                    if not is_text_file(rel_path):
                        continue

                    try:
                        # 读取文件内容
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                        files.append({
                            'path': rel_path.replace('\\', '/'),  # 统一使用/作为路径分隔符
                            'content': content
                        })
                    except Exception as e:
                        logger.debug(f"读取文件 {rel_path} 失败: {e}")
                        continue

            return files

        except Exception as e:
            logger.error(f"获取SSH仓库文件失败: {e}")
            raise
        finally:
            # 清理临时克隆目录
            if temp_clone_dir and os.path.exists(temp_clone_dir):
                shutil.rmtree(temp_clone_dir, ignore_errors=True)

    @staticmethod
    def test_ssh_key(repo_url: str, private_key: str) -> Dict[str, any]:
        """
        测试SSH密钥是否有效

        Args:
            repo_url: SSH格式的Git URL
            private_key: SSH私钥

        Returns:
            测试结果字典
        """
        from app.core.config import settings

        temp_dir = None
        try:
            # 从URL提取主机
            if '@' in repo_url:
                host_part = repo_url.split('@')[1].split(':')[0]
            else:
                return {'success': False, 'message': 'URL格式无效'}

            # 验证主机名格式（防止注入）
            if not re.match(r'^[\w\-\.]+$', host_part):
                logger.warning(f"Invalid host name rejected: {host_part}")
                return {'success': False, 'message': '无效的主机名'}

            # 创建临时目录存放密钥
            temp_dir = tempfile.mkdtemp(prefix='deepaudit_ssh_test_')
            key_file = os.path.join(temp_dir, 'id_rsa')

            # 写入私钥
            with open(key_file, 'w') as f:
                f.write(private_key)

            # 验证文件是否被创建
            if not os.path.exists(key_file):
                return {'success': False, 'message': '私钥文件创建失败'}

            set_secure_file_permissions(key_file)

            # 使用持久化的known_hosts文件
            known_hosts_file = get_known_hosts_file()

            # 构建SSH命令（使用列表形式避免shell注入）
            cmd = [
                'ssh',
                '-i', key_file,
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', f'UserKnownHostsFile={known_hosts_file}',
                '-o', f'ConnectTimeout={settings.SSH_CONNECT_TIMEOUT}',
                '-o', 'PreferredAuthentications=publickey',
                '-o', 'IdentitiesOnly=yes',
                '-v',
                '-T', f'git@{host_part}'
            ]

            logger.debug(f"Testing SSH connection to: {host_part}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=settings.SSH_TEST_TIMEOUT
            )

            # GitHub/GitLab/CodeUp的SSH测试通常返回非0状态码，但会在输出中显示认证成功
            output = result.stdout + result.stderr
            output_lower = output.lower()

            # 特别检查Anonymous（表示公钥未添加或未关联用户账户）
            if 'anonymous' in output_lower:
                return {
                    'success': True,
                    'message': 'SSH连接成功，但公钥未关联用户账户',
                    'output': '提示：服务器显示Anonymous,在使用部署密钥时是正常现象。\n请在Git服务的设置中添加SSH公钥。'
                }

            # 检查是否认证成功
            success_indicators = [
                ('successfully authenticated', True),
                ('hi ', True),
                ('welcome to gitlab', '@' in output),
                ('welcome to codeup', '@' in output),
            ]

            is_success = False
            for indicator, extra_check in success_indicators:
                if indicator in output_lower:
                    if extra_check is True or extra_check:
                        is_success = True
                        break

            if is_success:
                return {
                    'success': True,
                    'message': 'SSH密钥验证成功',
                    'output': output
                }
            else:
                # 提供更详细的错误信息
                error_msg = 'SSH密钥验证失败'
                if 'permission denied' in output_lower:
                    error_msg = 'SSH密钥验证失败：权限被拒绝，请确认公钥已添加到Git服务'
                elif 'connection refused' in output_lower:
                    error_msg = 'SSH连接被拒绝，请检查网络连接'
                elif 'no route to host' in output_lower:
                    error_msg = 'SSH连接失败：无法连接到主机'
                elif not output.strip():
                    error_msg = 'SSH连接失败：未收到任何响应'

                return {
                    'success': False,
                    'message': error_msg,
                    'output': output if output.strip() else '未收到任何响应'
                }

        except subprocess.TimeoutExpired:
            logger.warning(f"SSH test timeout after {settings.SSH_TEST_TIMEOUT}s")
            return {
                'success': False,
                'message': f'SSH连接超时（{settings.SSH_TEST_TIMEOUT}秒）',
                'output': '连接超时，请检查网络或Git服务可用性'
            }
        except Exception as e:
            logger.error(f"SSH test error: {e}")
            return {
                'success': False,
                'message': '测试失败，请稍后重试',
                'output': ''
            }
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
