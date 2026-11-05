#!/usr/bin/env bash
# 0_wheels_indir.sh
#
# INTERNETLİ bir bilgisayarda (Pardus/Linux, macOS, ya da Windows'ta Git
# Bash/WSL) çalıştırılır. Windows hedefi için gereken TÜM Python
# paketlerini (.whl) indirip bu klasördeki wheels/ içine koyar — pip'in
# "farklı platform için indirme" özelliği sayesinde bu, Windows'ta
# çalıştırmayı GEREKTİRMEZ.
#
# Kullanım:
#   python3 -m pip install --upgrade pip   # (gerekirse)
#   bash 0_wheels_indir.sh
#
# Bittikten sonra bu KLASÖRÜN TAMAMINI (0_wheels_indir.sh hariç, dilerseniz
# onu da bırakabilirsiniz) USB ile internetsiz Windows bilgisayara taşıyıp
# 1_kurulum.bat ile devam edin.

set -e
cd "$(dirname "$0")"

echo "Windows (Python 3.11, win_amd64) için paketler indiriliyor..."
python3 -m pip download \
  --python-version 3.11 --implementation cp --abi cp311 --platform win_amd64 \
  --only-binary=:all: --require-hashes \
  -d wheels \
  -r requirements.lock.txt

python3 -m pip download \
  --python-version 3.11 --implementation cp --abi cp311 --platform win_amd64 \
  --only-binary=:all: --require-hashes -d wheels -r requirements-dev.lock.txt || echo "UYARI: test paketleri indirilemedi (exe etkilenmez)."

echo ""
echo "Tamamlandı. wheels/ klasörü artık Windows'a taşınmaya hazır."
du -sh wheels 2>/dev/null || true
