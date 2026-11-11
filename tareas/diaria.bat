@echo off
REM Tarea diaria del gestor ML: registra ventas de ML en Supabase y sincroniza precio/stock hacia ML.
REM No usa Claude (cero tokens). Deja el registro en logs\diaria.log
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ================ %date% %time% ================>> logs\diaria.log
echo [1/3] Registrar ventas>> logs\diaria.log
python tools\ventas.py registrar --dias 3 >> logs\diaria.log 2>&1
echo [2/3] Estado de envios y fecha limite de despacho>> logs\diaria.log
python tools\ventas.py despachos >> logs\diaria.log 2>&1
echo [3/3] Sincronizar precio y stock>> logs\diaria.log
python tools\sync.py --aplicar >> logs\diaria.log 2>&1
echo Fin>> logs\diaria.log
