"""InkOS CLI 客户端

封装InkOS CLI命令的调用，提供异步Python接口。
支持重试机制和错误处理。
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class InkOSConfig:
    """InkOS配置"""
    max_retries: int = 2
    retry_delay: float = 5.0
    timeout: float = 120.0  # CLI命令可能需要较长时间


class InkOSError(Exception):
    """InkOS CLI执行错误"""
    def __init__(self, message: str, command: str, returncode: int, stderr: str):
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class InkOSClient:
    """InkOS CLI 客户端

    封装所有InkOS CLI命令的调用，支持：
    - 创建书籍
    - 写入章节
    - 导出内容
    - 获取真相文件
    - 审计和修订

    Example:
        client = InkOSClient()
        result = await client.create_book("我的小说", "xuanhuan")
        await client.write_chapters(result['book_id'], count=5)
    """

    def __init__(self, config: Optional[InkOSConfig] = None):
        """初始化客户端

        Args:
            config: InkOS配置，为None时使用默认配置
        """
        self.config = config or InkOSConfig()

    async def _run_command(self, cmd: str, parse_json: bool = True) -> Any:
        """执行CLI命令

        Args:
            cmd: 要执行的命令
            parse_json: 是否解析JSON输出

        Returns:
            解析后的JSON对象或原始输出字符串

        Raises:
            InkOSError: 命令执行失败
        """
        last_error = None

        for attempt in range(self.config.max_retries + 1):
            try:
                logger.debug(f"Executing command (attempt {attempt + 1}): {cmd}")

                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=self.config.timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    raise InkOSError(
                        message=f"Command timed out after {self.config.timeout}s",
                        command=cmd,
                        returncode=-1,
                        stderr="Timeout"
                    )

                stdout_str = stdout.decode('utf-8', errors='replace').strip()
                stderr_str = stderr.decode('utf-8', errors='replace').strip()

                if proc.returncode != 0:
                    raise InkOSError(
                        message=f"Command failed with return code {proc.returncode}",
                        command=cmd,
                        returncode=proc.returncode,
                        stderr=stderr_str
                    )

                # 解析输出
                if parse_json and stdout_str:
                    try:
                        return json.loads(stdout_str)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON output: {e}")
                        return stdout_str

                return stdout_str

            except InkOSError as e:
                last_error = e
                if attempt < self.config.max_retries:
                    logger.warning(
                        f"Command failed (attempt {attempt + 1}/{self.config.max_retries + 1}): {e.stderr}"
                    )
                    await asyncio.sleep(self.config.retry_delay)
                else:
                    logger.error(f"Command failed after all retries: {e.stderr}")
                    raise

        raise last_error

    async def create_book(self, title: str, genre: str = "other",
                          chapter_words: int = 3000,
                          target_chapters: Optional[int] = None) -> Dict[str, Any]:
        """创建新书

        Args:
            title: 书籍标题
            genre: 题材类型 (xuanhuan/xianxia/urban/horror/other)
            chapter_words: 每章字数
            target_chapters: 目标章节数

        Returns:
            包含book_id等信息的字典

        Raises:
            InkOSError: 创建失败
        """
        cmd = f"inkos book create --title '{title}' --genre {genre} --chapter-words {chapter_words}"
        if target_chapters:
            cmd += f" --target-chapters {target_chapters}"
        cmd += " --json"

        return await self._run_command(cmd)

    async def write_chapters(self, book_id: str, count: int = 1,
                             context: Optional[str] = None,
                             words: Optional[int] = None) -> Dict[str, Any]:
        """写入章节（完整管线：草稿→审计→修订）

        Args:
            book_id: 书籍ID
            count: 写入章节数
            context: 创作指导上下文
            words: 覆盖每章字数

        Returns:
            包含章节详情和质量指标的字典

        Raises:
            InkOSError: 写入失败
        """
        # 如果context很长，写入临时文件避免shell转义问题
        context_file = None
        if context and len(context) > 500:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(context)
                context_file = f.name

        try:
            cmd = f"inkos write next {book_id} --count {count}"
            if context_file:
                cmd += f" --context-file '{context_file}'"
            elif context:
                # 转义单引号
                escaped_context = context.replace("'", "'\\''")
                cmd += f" --context '{escaped_context}'"
            if words:
                cmd += f" --words {words}"
            cmd += " --json"

            return await self._run_command(cmd)
        finally:
            if context_file:
                import os
                os.unlink(context_file)

    async def draft_chapter(self, book_id: str, context: Optional[str] = None,
                            words: Optional[int] = None) -> Dict[str, Any]:
        """只生成草稿（不经过审计和修订）

        Args:
            book_id: 书籍ID
            context: 创作指导上下文
            words: 覆盖每章字数

        Returns:
            草稿内容

        Raises:
            InkOSError: 生成失败
        """
        cmd = f"inkos draft {book_id}"
        if context:
            escaped_context = context.replace("'", "'\\''")
            cmd += f" --context '{escaped_context}'"
        if words:
            cmd += f" --words {words}"
        cmd += " --json"

        return await self._run_command(cmd)

    async def audit_chapter(self, book_id: str, chapter: int) -> Dict[str, Any]:
        """审计指定章节

        Args:
            book_id: 书籍ID
            chapter: 章节号

        Returns:
            审计结果

        Raises:
            InkOSError: 审计失败
        """
        cmd = f"inkos audit {book_id} {chapter} --json"
        return await self._run_command(cmd)

    async def revise_chapter(self, book_id: str, chapter: int,
                             mode: str = "spot-fix") -> Dict[str, Any]:
        """修订指定章节

        Args:
            book_id: 书籍ID
            chapter: 章节号
            mode: 修订模式 (polish/spot-fix/rewrite/rework/anti-detect)

        Returns:
            修订结果

        Raises:
            InkOSError: 修订失败
        """
        cmd = f"inkos revise {book_id} {chapter} --mode {mode} --json"
        return await self._run_command(cmd)

    async def export_book(self, book_id: str, format: str = "txt") -> str:
        """导出书籍

        Args:
            book_id: 书籍ID
            format: 导出格式 (txt/md)

        Returns:
            导出的文件路径或内容

        Raises:
            InkOSError: 导出失败
        """
        cmd = f"inkos export {book_id} --format {format}"
        return await self._run_command(cmd, parse_json=False)

    async def get_status(self, book_id: Optional[str] = None) -> Dict[str, Any]:
        """获取项目状态

        Args:
            book_id: 书籍ID，为None时返回所有书籍状态

        Returns:
            状态信息

        Raises:
            InkOSError: 获取失败
        """
        cmd = "inkos status"
        if book_id:
            cmd += f" {book_id}"
        cmd += " --json"

        return await self._run_command(cmd)

    async def list_books(self) -> List[Dict[str, Any]]:
        """列出所有书籍

        Returns:
            书籍列表

        Raises:
            InkOSError: 获取失败
        """
        cmd = "inkos book list --json"
        result = await self._run_command(cmd)

        # 处理不同的返回格式
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and 'books' in result:
            return result['books']
        else:
            return [result] if result else []

    async def get_truth_files(self, book_id: str) -> Dict[str, str]:
        """获取真相文件内容

        Args:
            book_id: 书籍ID

        Returns:
            真相文件字典，key为文件名，value为内容

        Raises:
            InkOSError: 获取失败
        """
        # InkOS没有直接的真相文件导出命令，通过status获取路径
        status = await self.get_status(book_id)

        # 从状态中提取真相文件路径
        truth_files = {}
        truth_file_names = [
            'current_state.md',
            'particle_ledger.md',
            'pending_hooks.md',
            'chapter_summaries.md',
            'subplot_board.md',
            'emotional_arcs.md',
            'character_matrix.md'
        ]

        # 尝试读取真相文件
        import os
        book_path = status.get('path', '')
        if book_path:
            for file_name in truth_file_names:
                file_path = os.path.join(book_path, '.inkos', file_name)
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        truth_files[file_name] = f.read()

        return truth_files

    async def detect_aigc(self, book_id: str, chapter: Optional[int] = None,
                          all_chapters: bool = False) -> Dict[str, Any]:
        """AIGC检测

        Args:
            book_id: 书籍ID
            chapter: 指定章节号
            all_chapters: 是否检测所有章节

        Returns:
            检测结果

        Raises:
            InkOSError: 检测失败
        """
        cmd = f"inkos detect {book_id}"
        if all_chapters:
            cmd += " --all"
        elif chapter:
            cmd += f" {chapter}"
        cmd += " --json"

        return await self._run_command(cmd)

    async def import_style(self, reference_file: str, book_id: str,
                           name: Optional[str] = None) -> Dict[str, Any]:
        """导入文风

        Args:
            reference_file: 参考文本文件路径
            book_id: 书籍ID
            name: 风格名称

        Returns:
            导入结果

        Raises:
            InkOSError: 导入失败
        """
        cmd = f"inkos style import '{reference_file}' {book_id}"
        if name:
            cmd += f" --name '{name}'"
        cmd += " --json"

        return await self._run_command(cmd)

    async def agent_command(self, instruction: str) -> Dict[str, Any]:
        """自然语言Agent模式

        Args:
            instruction: 自然语言指令

        Returns:
            执行结果

        Raises:
            InkOSError: 执行失败
        """
        escaped_instruction = instruction.replace("'", "'\\''")
        cmd = f"inkos agent '{escaped_instruction}'"
        return await self._run_command(cmd)
