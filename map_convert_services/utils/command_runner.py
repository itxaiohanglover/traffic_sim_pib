import subprocess
import os
import time
from pathlib import Path
from typing import List, Literal
import datetime
import threading
import sys


async def RunExe(
        cmd: List[str],
        log_file: str = None,
        output_mode: Literal["file", "console", "both"] = "both"
) -> str:
    """启动一个进程，支持多种输出模式（Linux/Wine 版本）

    Args:
        cmd (List[str]): 启动命令
        wait (bool, optional): 是否阻塞等待并返回进程输出
        log_file (str, optional): 日志文件路径
        output_mode (str): 输出模式，可选值:
            - "file": 仅输出到日志文件
            - "console": 仅显示终端窗口
            - "both": 同时输出到日志文件和终端窗口

    Returns:
        str: 进程输出或状态信息
    """
    process = None
    log_handle = None

    try:
        # 验证输出模式
        if output_mode not in ["file", "console", "both"]:
            return f"错误: 无效的输出模式 '{output_mode}'，应为 'file', 'console' 或 'both'"

        # 检查日志文件参数
        if output_mode in ["file", "both"] and not log_file:
            return "错误: 在 'file' 或 'both' 模式下必须提供 log_file 参数"

        # 使用绝对路径
        if cmd[0].startswith('./') or cmd[0].startswith('.\\'):
            abs_path = os.path.abspath(cmd[0])
            cmd[0] = abs_path
            print(f"使用绝对路径: {abs_path}")

        # 检查文件是否存在
        if not os.path.exists(cmd[0]):
            error_msg = f"错误: 可执行文件不存在 - {cmd[0]}"
            print(error_msg)
            if output_mode in ["file", "both"]:
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write(error_msg)
            return error_msg

        # 在 Linux 中，.exe 文件本身不可执行，需要通过 Wine 运行
        # 所以我们跳过可执行权限检查

        # 准备日志文件
        if output_mode in ["file", "both"]:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_file, 'w', encoding='utf-8')
            log_handle.write(f"启动命令: {' '.join(cmd)}\n")
            log_handle.write(f"工作目录: {os.getcwd()}\n")
            log_handle.write(f"输出模式: {output_mode}\n")
            log_handle.write(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_handle.write(f"平台: {sys.platform}\n")
            log_handle.write("-" * 80 + "\n")
            log_handle.flush()

        # 如果是 .exe 文件，通过 Wine 运行
        if cmd[0].lower().endswith('.exe') and sys.platform != 'win32':
            wine_cmd = ['wine'] + cmd
            if output_mode in ["file", "both"] and log_handle:
                log_handle.write(f"通过 Wine 执行: {' '.join(wine_cmd)}\n")
                log_handle.flush()
            cmd = wine_cmd

        # 根据平台设置 subprocess 参数
        stdout_dest = subprocess.PIPE
        stderr_dest = subprocess.PIPE
        creation_flags = 0

        # Linux 下没有 CREATE_NEW_CONSOLE，使用其他方式处理输出
        if sys.platform != "win32":
            # 在 Linux 下，我们可以使用 setsid 来创建新的进程组
            creation_flags = os.setsid
        else:
            # 在 Windows 下保留原来的逻辑
            if output_mode in ["console", "both"]:
                creation_flags = subprocess.CREATE_NEW_CONSOLE

        # 启动进程
        process_kwargs = {
            'stdout': stdout_dest,
            'stderr': stderr_dest,
            'stdin': subprocess.PIPE,
            'text': True,
            'bufsize': 1,
            'universal_newlines': True
        }

        # 根据平台添加适当的参数
        if sys.platform == "win32":
            process_kwargs['creationflags'] = creation_flags
        else:
            process_kwargs['preexec_fn'] = creation_flags

        process = subprocess.Popen(cmd, **process_kwargs)

        # 实时读取输出的函数
        def read_output(pipe, pipe_name, log_handle, output_mode):
            try:
                for line in iter(pipe.readline, ''):
                    line = line.rstrip()  # 移除行尾空白字符
                    if line:
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                        output_line = f"[{timestamp}] [{pipe_name}] {line}\n"

                        # 根据输出模式决定如何处理输出
                        if output_mode in ["file", "both"] and log_handle:
                            log_handle.write(output_line)
                            log_handle.flush()

                        # 对于文件模式，也在控制台显示（便于调试）
                        if output_mode == "file" or output_mode == "both":
                            print(output_line, end='')
                pipe.close()
            except Exception as e:
                error_msg = f"读取{pipe_name}时出错: {e}\n"
                print(error_msg)
                if output_mode in ["file", "both"] and log_handle:
                    log_handle.write(error_msg)
                    log_handle.flush()

        # 只有在需要捕获输出时才启动读取线程
        if output_mode in ["file", "both"]:
            stdout_thread = threading.Thread(
                target=read_output,
                args=(process.stdout, "STDOUT", log_handle, output_mode)
            )
            stderr_thread = threading.Thread(
                target=read_output,
                args=(process.stderr, "STDERR", log_handle, output_mode)
            )

            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

        # 等待更长时间并检查进程状态
        time.sleep(3)

        if process.poll() is None:  # 进程仍在运行
            pid_info = f"进程已启动，PID: {process.pid}"
            print(pid_info)
            if output_mode in ["file", "both"] and log_handle:
                log_handle.write(pid_info + "\n")
                log_handle.flush()
            return f"ok - PID: {process.pid}"
        else:
            return_code = process.returncode
            error_info = f"进程立即退出，返回码: {return_code}"

            # 添加 Wine 特定的错误解释
            error_explanations = {
                0xC0000135: "应用程序无法正确启动 - 通常是由于缺少依赖的DLL文件或Visual C++ Redistributable未安装",
                0xC0000142: "DLL初始化失败",
                0xC000007B: "应用程序无法正确启动 - 通常是由于32位/64位不兼容",
                127: "Wine: 命令未找到或无法执行",
                126: "Wine: 权限问题或文件格式错误",
            }

            explanation = error_explanations.get(return_code, "未知错误")
            full_error = f"{error_info}\n错误解释: {explanation}"

            print(full_error)
            if output_mode in ["file", "both"] and log_handle:
                log_handle.write(full_error + "\n")
                log_handle.flush()
                if log_handle:
                    log_handle.close()

            return full_error

    except Exception as e:
        error_msg = f"启动进程时发生错误: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        if output_mode in ["file", "both"] and log_handle:
            log_handle.write(f"EXCEPTION: {error_msg}\n")
            log_handle.write(traceback.format_exc())
            if log_handle:
                log_handle.close()
        return error_msg