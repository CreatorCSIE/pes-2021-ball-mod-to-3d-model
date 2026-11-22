@echo off
rem PES ball mod 转换入口（Windows）。参数原样透传给 scripts\pes_ball_convert.py
rem 示例（输入为任意已解包的 mod 目录，路径含空格时加引号）:
rem   convert.bat "X:\解包目录\content\omb\球名\Asset\model\ball\ballNNN\#Win\ball.fpk"
rem   convert.bat "X:\解包目录\content\omb" -o output
where python >nul 2>nul || (echo 未找到 python，请安装 Python 3 并加入 PATH >&2 & exit /b 1)
python "%~dp0scripts\pes_ball_convert.py" %*
