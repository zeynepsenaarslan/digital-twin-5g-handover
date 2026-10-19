# Phase C2.3: CSV verilerinden bilimsel şekiller

C++ simülasyonu ve eski CSV dosyaları değiştirilmez. Phase C2.2 SINR kaydı
yoktur; bu modül SINR üretmez veya çizmez. Beş şekil PNG (300 DPI) ve SVG
olarak kaydedilir. Arayüz, grafik penceresi gerektirmeyen Agg backend kullanır.

## Ortam ve bağımlılıklar

Sistem Python'unda Matplotlib yoktu. Proje içinde `.venv-analysis` oluşturuldu;
bu dizin `.gitignore` içinde hariç tutulur. Sistem Python'una paket kurulmadı.
İlk kısıtlı ağ denemesi başarısız oldu; onaylanan ağ erişimiyle venv kurulumu
başarılı tamamlandı. Test edilen Matplotlib sürümü **3.11.2**.

```bash
python3 -m venv .venv-analysis
.venv-analysis/bin/python -m pip install -r analysis/requirements-lock.txt
```

`requirements.txt` doğrudan bağımlılığı; `requirements-lock.txt` test edilen
Matplotlib ve transitif bağımlılıkların tam sürümlerini kaydeder.

## Dosya düzeni ve yeniden üretim

- `phase_c23_plots.py`: CSV doğrulama, veri hizalama, grafik üretimi ve rapor.
- `test_phase_c23_plots.py`: eksik kolon, boş veri, geçersiz değer, birim ve
  farklı koşuların yanlış birleştirilmesini yakalayan yedi test.
- Her çıktı dizini: beş PNG, beş SVG, `report.md`, `plot_manifest.json`.

Proje kökünde aşağıdaki komutu çalıştırın. Kullanılan output dizini artık
mevcutsa betik durur; her çalıştırmada yeni bir ad seçin.

```bash
tag=$(date +%Y%m%d-%H%M%S)
.venv-analysis/bin/python -B analysis/phase_c23_plots.py \
  --radio-run dt-output/phase-c21-20261017-170148-b3-45s \
  --qos-dir dt-output/phase-c1-20261017-final-b3-100ms \
  --output-dir "dt-output/phase-c23-${tag}-plots" \
  --zoom-seconds 1

.venv-analysis/bin/python -B -m unittest discover \
  -s analysis -p 'test_phase_c23_plots.py' -v
```

Doğrulanan ilk şekiller: `dt-output/phase-c23-20261017-plots/`.
Burada ek olarak `validation.json` bağımsız dosya/çözünürlük kontrollerini içerir.

Yeni simülasyon sonuçlarından önce yeni QoS dosyalarını oluşturun:

```bash
.venv-analysis/bin/python -B analysis/phase_c1_qos.py \
  --input-dir dt-output/YENI_RADYO_KOSUSU \
  --output-dir dt-output/YENI_QOS_ANALIZI --window-ms 100
.venv-analysis/bin/python -B analysis/phase_c23_plots.py \
  --radio-run dt-output/YENI_RADYO_KOSUSU \
  --qos-dir dt-output/YENI_QOS_ANALIZI \
  --output-dir dt-output/YENI_SEKILLER
```

Bu büyük harfli adlar yer tutucudur; gerçek yeni dizinlerinizle değiştirin.
Betik radyo koşusundaki özgün paket CSV'siyle C1 kayıtlarını karşılaştırır;
farklı deneylerin fark edilmeden aynı şekle konulmasını reddeder.

## Matplotlib kavramları

CSV'yi Matplotlib'in kendisi okumaz: `csv.DictReader` satırları sözlük olarak
okur; sayısal alanlar kontrol edilip sayılara çevrilir. Matplotlib bu dizileri
kullanır. Pandas veya başka veri analizi paketi gerekmez.

- `figure`: çizimin tamamı; sayfa/tuval gibi düşünülebilir.
- `axes`: bu tuvaldeki bir grafik alanı; x/y eksenleri, başlık ve seriler buradadır.
- `plot(x, y)`: varsayılan olarak noktaları çizgilerle birleştirir.
- `scatter(x, y)`: yalnız verilen noktalara işaret koyar. Radyo ve gecikme
  grafiklerinde, örnekler arasına ölçüm varmış izlenimi vermemek için kullanıldı.
- `bar(...)`: goodput'un gerçek analiz penceresini dikdörtgen olarak gösterir.
- `legend()`: serilerin `label` açıklamalarını gösterir.
- `savefig(...)`: tuvali PNG/SVG gibi bir dosyaya kaydeder.
- `axvline(...)`: kayıtlı olay zamanı için dikey işaret çizer.

Basit kullanım örneği (mevcut modülde `fig, ax = plt.subplots(...)` şeklinde):

```python
fig, ax = plt.subplots()
ax.scatter(times, values, marker='o', s=12, label='Gerçek ölçümler')
ax.set_title('Yeni başlık')
ax.set_xlabel('Simulation time (s)')
ax.set_ylabel('PHY RSRP (dBm)')
ax.legend()
fig.savefig('yeni_sekil.png', dpi=300)
```

Başlık ve eksen adlarını modüldeki `set_title`, `set_ylabel` veya `set(...)`
çağrılarından değiştirebilirsiniz. `EVENTS` sözlüğündeki `--`, `:` ve `-.`
olay çizgilerinin stilidir. Radyo noktalarının biçimi `plot_radio` içindeki
`marker`, `s`, `facecolors` ve `edgecolors` ile belirlenir.

## Ölçüm anlamı ve görsel kodlama

RSRP rengi ölçülen hücreyi, dolu daire serving rolünü, boş üçgen neighbour
rolünü gösterir. Bir hücrenin rolü handover sonrasında değişebilir.
RSRQ etiketi açıkça model-derived'dır; standarda uygunluğunun bağımsız olarak
doğrulandığı iddia edilmez. Kuantize RRC RSRP raporları bu şekillerde kullanılmaz.

Gecikmenin x ekseni paketin UE'ye alım zamanıdır. Goodput ise C1'in gerçek
100 ms pencerelerindeki alınan UDP baytlarından gelir; SeqTsHeader dahil,
UDP/IP/link başlıkları hariçtir. PHY/MAC throughput olarak adlandırılmaz.

Boş değerler eksiktir ve çizilmez; sayısal sıfırlar korunur. Enterpolasyon veya
forward-fill yapılmaz. Olay zamanları yalnız `handover_events.csv` dosyasından
okunur; UE başlangıcı, UE tamamlanması ve hedef gNB tamamlanması ayrı etiketlidir.

`RADIO_METRICS` metadata sözlüğü ileride doğrulanmış yeni radyo metrikleri için
genişletilebilir. SINR şu anda bu sözlükte yoktur. Yeni bir metrik kendiliğinden
tahmin edilmez; bilinmeyen metrikler doğrulanmış metadata eklenene kadar reddedilir.

## Bu koşunun doğrulaması ve yorumu

- PASS: 900 radyo satırı, 0.2..45 s; RSRP ve RSRQ için 450'şer nokta.
- PASS: 4299 paket gecikmesi, 1.002707141..43.992707141 s.
- PASS: 450 goodput penceresi, 0..45 s.
- PASS: Üç olay zamanı CSV ile aynı: 40.742171427, 40.744035713, 40.748564480 s.
- PASS: Beş PNG (300 DPI) ve beş SVG üretildi, dosya formatları kontrol edildi.
- PASS: Yedi otomatik test; özgün 16 kaynak/sonuç dosyasının SHA-256 özeti aynı.
- PASS: Mevcut çıktı dizinine yeniden yazma girişimi reddedildi.

Handover çevresindeki radyo noktalarında hücre 2 daha güçlü görünür ve serving
rolü hücre 1'den 2'ye geçer. Paket gecikmesi 2.707141..5.207141 ms aralığındadır.
Başlangıcı içeren [40.7,40.8) s goodput penceresinde 9 paket ve 0.368640 Mbit/s
görülür. Bu, paket kaydıyla zaman açısından tutarlıdır; tek başına kaybın
katmanını veya nedenini kanıtlamaz. 200 ms radyo örneklemesi milisaniyelik
handover aşamalarını çözemez. Alım boşluğu standart handover interruption time
değildir. Bu görselleştirme 30 s ile 45 s koşularını nedensel karşılaştırmaz.
