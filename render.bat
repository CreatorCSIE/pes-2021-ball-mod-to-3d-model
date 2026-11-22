@echo off
rem AI 生图素材渲染入口（Windows）。参数为 <glb> <outdir> [选项]，见 blender_render_pack.py
rem 用法:
rem   set BLENDER=<blender.exe 路径>（或将 blender 加入 PATH 后免设）
rem   render.bat "output\Puma_...\Puma_....glb" "output\Puma_..." --passes
setlocal
if "%BLENDER%"=="" (
  where blender >nul 2>nul
  if errorlevel 1 (echo 请设置 BLENDER 环境变量为 blender.exe 路径，或将 blender 加入 PATH >&2 & exit /b 1)
  set "BLENDER=blender"
)
"%BLENDER%" -b -P "%~dp0scripts\blender_render_pack.py" -- %*
