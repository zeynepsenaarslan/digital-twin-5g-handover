# Phase C2.1: pasif RSRP/RSRQ kaydı

Bu aşama yalnız kurulu `NrUePhy::ReportUeMeasurements` trace kaynağını dinler.
Hareket, trafik, kanal, RNG, A3, hysteresis, TTT ve ölçüm aralığı değiştirilmez.
Genie callback etkinleştirilmez. SINR veya görselleştirme eklenmez.

## Trace ve callback

Trace source, ns-3 nesnesinin bir olay oluştuğunda ilgilenen dinleyicilere veri
verdiği bağlantı noktasıdır. Callback ise bu olayda çağrılan C++ fonksiyonudur.
Burada PHY zaten ölçüm yapmaktadır; dinleyici yalnız verilen değerleri kaydeder.

Kurulu kaynak: `contrib/nr/model/nr-ue-phy.cc:208` (trace kaydı),
`contrib/nr/model/nr-ue-phy.h:511` (kesin imza),
`contrib/nr/model/nr-ue-phy.cc:1766` (trace çağrısı).

```cpp
void(uint16_t rnti, uint16_t cellId, double rsrp, double rsrq,
     bool isServingCell, uint8_t componentCarrierId)
```

`cellId` ölçülen hücredir. RSRP, lineer güç ortalamasından elde edilen dBm;
RSRQ kurulu modelin güç/gürültü haritasından hesapladığı dB değeridir.
Bu değerler RRC'nin filtrelenmiş/kuantize rapor IE değerleri değildir.
Model RSRQ hesabının standarda uygunluğu bu aşamada ayrıca doğrulanmamıştır.

## Eklenen C++ parçaları

`scratch/dt-handover-simulation.cc:35`: `RadioMeasurementLogger` sınıfı.

- Constructor dosyayı açar ve başlığı yazar.
- `Record` (satır 61) gerçek callback verilerini alır. Ek ilk iki argüman
  UE nesnesi ve mobility CSV'sindeki UE indeksidir; `.Bind(device, i)` bu
  argümanları önceden bağlar. Trace yalnız yukarıdaki altı argümanı gönderir.
- `Write` (satır 96) bir metrik satırı yazar. Her çağrı RSRP ve RSRQ için
  iki satır üretir; ölçümler çoğaltılmaz veya sentetik örnek üretilmez.
- `Close` (satır 75) dosya kapatılırken yazma hatasını kontrol eder.
- Satır 615'ten itibaren UE/BWP PHY nesnesine `TraceConnectWithoutContext`
  ile bağlanılır. `MakeCallback` C++ metodu ile logger nesnesini eşler.

IMSI trace'te olmadığından UE'den `uint64_t` olarak okunur. Serving hücre,
trace'in flag hesabıyla aynı BWP PHY nesnesinden okunur. Getter çağrıları
durumu değiştirmez; callback hiçbir event planlamaz ve RNG çağırmaz.

## Yeni CSV: radio_measurements.csv

| Kolon | Anlam |
|---|---|
| time_ns | Tam sayı simülasyon zamanı, nanosaniye |
| time_s | Aynı zaman, saniye |
| ue_id | Mobility CSV ile aynı UE indeksi |
| imsi | UE abone kimliği; 64 bit |
| rnti | PHY'nin o anda bildirdiği radyo kimliği |
| bwp_id | Bildirilen BWP/component carrier indeksi |
| serving_cell_id | O BWP PHY'sinin güncel serving hücresi |
| measured_cell_id | Ölçülen hücre |
| is_serving | Trace'in serving flag'i: 1 serving, 0 neighbour |
| metric | rsrp veya rsrq_model_derived |
| value | Trace'in verdiği değiştirilmemiş double değer |
| unit | RSRP için dBm, RSRQ için dB |
| source | NrUePhy::ReportUeMeasurements |

Zamanlar her UE/IMSI/BWP/ölçülen hücre/metrik akışında azalmamalıdır.
Aynı anda farklı hücre ve metrik satırları olması normaldir. Daha sık örnek
elde etmek için PHY raporlama aralığı değiştirilmemiştir; mevcut aralık 200 ms.

## Kullanılan koşular ve sonuçlar

```bash
./ns3 run 'dt-handover-simulation --enableHandover=0 --simTime=30 --outputDir=dt-output/phase-c21-20261017-170148-baseline30' --no-build
./ns3 run 'dt-handover-simulation --enableHandover=1 --simTime=45 --outputDir=dt-output/phase-c21-20261017-170148-b3-45s' --no-build
```

Bu dizinler artık mevcuttur; yeniden çalıştırırken yeni outputDir kullanın.

| Kontrol | Baseline 30 s | B3 45 s |
|---|---|---|
| A/B1/B2 | PASS | PASS |
| B3 | Kapalı | PASS |
| Mobility örneği | 1001 | 1501 |
| UDP TX/RX/kayıp | 2800/2800/0 | 4300/4299/1 |
| Radyo satırı | 600 | 900 |
| Gerçek hücre ölçümü | 300 | 450 |
| İlk/son ölçüm | 0.2 / 30 s | 0.2 / 45 s |
| Önceki beş CSV ile byte karşılaştırması | PASS | PASS |

B3 UE başlangıç: 40.742171427 s, UE tamamlanması: 40.744035713 s,
hedef gNB tamamlanması: 40.748564480 s. Önceki B3 ile aynı.
40.8 s'de serving hücre 2, measured hücre 1 için flag 0, hücre 2 için flag 1.
Mevcut tek UDP kaybı değişmedi; kaybın kesin alt katman nedeni iddia edilmez.

## Derleme notu

`./ns3 build dt-handover-simulation -j 1` tüm bağımlılıklar için 1185 iş
planladığından durduruldu; tam bağımlılık yeniden derlemesi tamamlandı denmez.
Mevcut kütüphaneler kullanılarak simülasyon nesnesi başarıyla derlendi:

```bash
ninja -C cmake-cache -j 1 scratch/CMakeFiles/scratch_dt-handover-simulation.dir/dt-handover-simulation.cc.o
```

Bağlantı komutu `ninja -C cmake-cache -t commands scratch_dt-handover-simulation`
çıktısının son satırından alındı; `shlex.split` ile ayrılarak `/usr/bin/c++`
argüman listesi `cmake-cache` çalışma dizininde çalıştırıldı. Bağlantı başarılı.
Tam komut B3 sonuç dizinindeki `build-link-command.txt` dosyasında korunmuştur.

Sarmalayıcının oluşturulmuş build kaydı debug iken mevcut CMake cache release
olduğundan ilk run girişimi executable bulamadı. `cmake -S . -B cmake-cache`
mevcut ayarlarla tekrar çalıştırılarak oluşturulan kayıt release ile eşitlendi;
ardından yukarıdaki standart ns3 run komutları başarılı oldu. Kaynak CMake
dosyalarında değişiklik yapılmadı. Examples ve tests açık kaldı.

## Kendiniz kontrol edin

```bash
head -n 9 dt-output/phase-c21-20261017-170148-b3-45s/radio_measurements.csv
python3 -B analysis/validate_phase_c21_radio.py --run-dir dt-output/phase-c21-20261017-170148-b3-45s --reference-dir dt-output/phase-b3-20261013-204213-final45
python3 -B analysis/validate_phase_c21_radio.py --run-dir dt-output/phase-c21-20261017-170148-baseline30 --reference-dir dt-output/phase-b3-20261013-204213-final-baseline30
```

Validator bu projenin tek UE, iki hücre ve tek BWP senaryosuna özeldir.
Şema, birim, sonlu değer, tam zaman birimi, monotonic stream, metrik çifti,
serving/neighbour eşleşmesi ve handover sonrası hedef serving ölçümleri kontrol
edilir. Eski mobility/UDP/RRC CSV'leri referansla byte düzeyinde karşılaştırılır.
Geçersiz birim, NaN, flag, şema ve zaman sırası içeren geçici kopyalarla beş
negatif kontrol de geçti. Eski B3/C1 çıktıları ve yedek dahil 58 dosyanın
SHA-256 özeti değişmedi. Kanıtlar sonuç dizinlerinde JSON olarak saklandı.

Yedek: `research-backups/dt-handover-simulation-before-c21-20261017-170148-427508.cc`.
Eklenen Python validator: `analysis/validate_phase_c21_radio.py`.
Phase C2.2 veya C2.3 uygulanmadı. Tek koşu genel handover güvenilirliğini kanıtlamaz.
