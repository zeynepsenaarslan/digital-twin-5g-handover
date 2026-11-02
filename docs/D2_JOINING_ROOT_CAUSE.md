# D2 UE1 joining timeout: hipotez, kanit, duzeltme ve regresyon

Tarih: 2026-11-02. Sonuc: **joining hatasinin nedeni kanitlandi; acik 23 dBm
D2 profilinde duzeltme dogrulandi. D2 asamasinin tamami tamamlandi isaretlenmedi.**
Eski 2 dBm kosulunda hata korunuyor ve yeniden uretilebiliyor. Bu bir native
context yonetimi programlama hatasi duzeltmesi degil, D2'nin devraldigi yetersiz
uplink guc butcesini acikca tanimlayan senaryo duzeltmesidir.

## Hipotezler

| Hipotez | Sonuc | Kanit |
|---|---|---|
| Hedef context, joining timeout'tan once siliniyor | Curutuldu | Timeout callback'inde present=1/state=8; silme ayni yordamda daha sonra |
| HO command veya random access teslim olmuyor | Curutuldu | UE SRB1 command RX, RRC 9->10, RAR ve RA_SUCCESS mevcut |
| Reconfiguration-complete hic olusturulmuyor veya UL grant yok | Curutuldu | UE PDCP TX 3 bayt, RLC TX 7 bayt, UL grant ve gercek PHY TX mevcut |
| Baskin hucresel girisim UL'yi bozuyor | Bu olay icin desteklenmedi | 53/53 RB'de native SNR ve SINR kaydedilen hassasiyette ayni |
| Devralinan sabit 2 dBm / kapali UL power control butcesinde SRB1 UL noise-limited | Kanitlandi | 40/40 TB bozuk, hedef RLC/PDCP RX=0; ayni olayda 21 dB guc adimi ilk TB'yi duzeltiyor |

SNR/SINR karsilastirmasi yalnizca ayni tam bantli 53 RB / ayni zaman olaylari
icin yapildi. Trace sayilari alti ondalikta kaydediliyor; esitlik bu hassasiyet
icindir. Sonuc tum agin her zaman girisimsiz oldugu anlamina gelmez. Dusuk
alinan gucun ayri path-loss/shadowing/fading/anten katkilarini ayristirmadik.

## Kanit: son basarili HO'dan basarisiz altinci girisime

UE index=1, IMSI=4. RNTI hucreseldir; asagidaki baglar IMSI + hucre + RNTI
ve UE-local attempt_id ile kuruldu. Saniyeler simulator zamanidir.

| Zaman (s) | Native olay ve kimlik |
|---:|---|
|37.320064281|HO5 icin source cell2/RNTI3 X2 HO Request TX; source RRC 4->7 |
|37.320064459|Target cell3/RNTI4 context olusturuldu, HANDOVER_JOINING=8; ayni zamanda IMSI4 tanimlandi, X2 ACK TX |
|37.320064574|Source X2 ACK RX; SRB1 HO command dispatch; source 7->10 |
|37.322171427|UE HO5 start, cell2 -> cell3; command RLC/PDCP tarafinda alindi |
|37.324035713|RA basarili, UE completion SRB1'e verildi; UE 10->9 / EndOk |
|37.328564281|Target cell3 RRC complete aldi; joining timer iptal; state 8->9 |
|37.328564480|Path switch tamamlandi; target 9->4 / gNB EndOk; X2 UE Context Release TX |
|37.328564513|Eski cell2/RNTI3 context NotifyConnectionRelease ve map erase |
|49.540064281|Cell3/RNTI4, A3 raporunu alip HO6 X2 Request gonderdi; state 4->7 |
|49.540064459|Cell2/RNTI5 context olusturuldu (state=8), IMSI4 atandi, ACK gonderildi ve 200 ms joining watchdog kuruldu |
|49.540064574|Cell3 X2 ACK RX, PDCP HO command TX (87 bayt); source 7->10; SN Status Transfer TX |
|49.540064608|Cell2 SN Status Transfer RX |
|49.541000000|Source SRB1 RLC command TX (91 bayt) |
|49.542171427|UE RLC command RX (91), PDCP RX (87), RRC 9->10; target cell2/RNTI5 preamble TX; yeni SRB1 olustu |
|49.543000000|Target ilk RA/UL grant kaydi (20 bayt) |
|49.544035713|RAR RX, RA_SUCCESS; UE PDCP completion TX (3 bayt), RRC 10->9 ve UE EndOk |
|49.544500000|UE scheduling request TX |
|49.546000000|Target UL grant (43 bayt; RV0) |
|49.547035713|UE grant RX; SRB1 RLC TX (7 bayt: 3-byte PDCP PDU + AM header) |
|49.548321427|Gercek UE UL PHY TX, toplam PSD gucu 2 dBm |
|49.548464281|Ilk UL TB bozuk: SNR=SINR=0.007490, TBLER=1; RV0 |
|49.550964281 ve sonrasi|HARQ RV1/2/3 ve RLC yeniden iletimleri de hedefte cozumlenemiyor |
|49.740064459|Joining watchdog fires: target context HALA mevcut, state=8; native HandoverFailureJoining |
|49.740064459|Target X2 unsuccessful HO preparation outcome TX; NotifyConnectionRelease callback'inde context HALA mevcut |
|49.740064459|Ayni native event icinde m_ueMap.erase; ScheduleNow gozleminde present=0 |
|49.740064493|Source cell3 X2 failure RX; HANDOVER_LEAVING dalinda leaving timer iptal edilir |
|90.000000001|UE hala cell2/RNTI5 CONNECTED_NORMALLY bildirirken hedef context yok |

**Onemli duzeltme:** HandoverFailureJoining aninda context bulunamiyor iddiasi
dogru degildir. Trace tetiklenirken context vardir; timeout'un kendi cleanup'i
siler. Kosu sonu yoklugu neden degil, teslim basarisizliginin sonucudur.

Basarisiz joining penceresinde 10 SRB1 RLC TX ve 40 ayri PHY TB goruldu;
hepsi bozuk. Hedef SRB1 RLC RX=0, PDCP RX=0, RRC complete RX=0. Native
RxPacketTraceGnb ayni TB icindeki her packet icin calistigindan 80 trace satiri
vardir; bunlar 80 ayri TB veya callback kaydi hatasi diye sayilmadi.
SNR araligi yaklasik -21.4327 ile -18.3615 dB; gercek UL TX hep 2 dBm.

UE EndOk hedefin RRC complete aldigini kanitlamaz: UE native callback'i mesaji
SRB1'e verdikten sonra UE'yi CONNECTED_NORMALLY'ye gecirir. RAR/control
basarisi da PUSCH veri TB'sinin basariyla cozumlendigini kanitlamaz.

Source tarafinda ayri bir recovery siniri goruluyor: HANDOVER_LEAVING durumunda
X2 failure alininca leaving timer iptal ediliyor, fakat UE'yi source'a geri
getiren bir recovery/state transition burada uygulanmiyor. Bu native sinir
D1 davranisini degistirecek sekilde yamalanmadi; 2 dBm hata deneyi icin
sinir olarak korunuyor. Timeout veya cleanup kaldirilarak sonuc gizlenmedi.

## Native kaynak tetikleme ve teslim noktalari

Referanslar bu calismada degistirilmeyen yerel ns-3 3.48 / NR v5.0 kaynagidir.

- `contrib/nr/model/nr-gnb-rrc.cc:3091`: X2 request RX, AddUe(HANDOVER_JOINING), sonra source/IMSI atamasi. NewUeContext trace'inde IMSI'nin ilk anda 0 olmasi bu siradandir; ayni cell/RNTI sonraki gozlemde IMSI4'e baglanir.
- `contrib/nr/model/nr-gnb-rrc.cc:3166`: ACK gonderildikten sonra StartHandoverJoiningTimer.
- `contrib/nr/model/nr-gnb-rrc.cc:1799`: native watchdog Schedule; `contrib/nr/model/nr-gnb-rrc.cc:2045`: degismeyen 200 ms varsayilani.
- `contrib/nr/model/nr-ue-rrc.cc:787`: RA sonrasi completion gonderimi ve UE state/EndOk sirasi.
- `contrib/nr/model/nr-rrc-protocol-real-ue.cc:145`: completion encode, LCID1 SRB1 PDCP'ye teslim. Trace size/time baglantisi bu native cagri yoluyla kuruldu; PDCP trace'i dogrudan packet/header vermiyor.
- `contrib/nr/model/nr-spectrum-phy.cc:1660`: native BLER/random corruption karari; `contrib/nr/model/nr-spectrum-phy.cc:1780`: yalniz bozuk olmayan TB paketini ust katmana teslim.
- `contrib/nr/model/nr-interference.cc:94`: native SNR=S/N; `contrib/nr/model/nr-interference.cc:134`: native SINR=S/(I+N).
- `contrib/nr/model/nr-gnb-rrc.cc:1322`: completion alinsaydi HANDOVER_JOINING dalinda watchdog iptal edilirdi.
- `contrib/nr/model/nr-gnb-rrc.cc:2812`: asil HandoverFailureJoining tetik noktasi; GetUeManager ile context okunur, failure trace cagrilir, X2 failure gonderilir, RemoveUe cagrilir.
- `contrib/nr/model/nr-gnb-rrc.cc:3525`: pending timer cancellation, NotifyConnectionRelease, sonra map erase.
- `contrib/nr/model/nr-gnb-rrc.cc:1080`: source HANDOVER_LEAVING recovery siniri.
- `contrib/nr/model/nr-ue-phy.cc:81`: devralinan TxPower=2 dBm; `contrib/nr/model/nr-ue-phy.cc:131`: UL power control varsayilani false.
- `contrib/nr/model/nr-epc-x2-header.h:70`: kaydedilen X2 procedure/type kodlari.

## Duzeltmeden once nedensel deney

`--ueTxPower=2 --diagnoseJoining=1 --joiningPowerProbe=1`, seed/run 1/1.
Bu yalnizca acikca secilen bir deneydir, normal profil veya pasif logger degildir.
Diger UE'ler 2 dBm kaldi. Yalniz UE1'in ayni RA_SUCCESS olayinda,
49.544035713 s'de, 2 -> 23 dBm adimi uygulandi.

- Deneyden onceki **10,106 timeline satiri**, tum alanlari ve sirasi dahil baseline ile birebir ayni.
- Ilk ayni UL TB'de SNR/SINR 0.007490 -> 0.942922; olculen artis 20.99994 dB.
- TB corrupt=1 -> 0; hedef RLC 7 bayt ve PDCP 3 bayti 49.548564281 s'de aldi.
- Hedef RRC complete RX 49.548564281 s; state 8->9, native watchdog iptal.
- Path switch/gNB EndOk 49.548564480 s; state 9->4. Eski source context normal X2 release yoluyla silindi.
- HO6 joining timeout artik olusmadi. Watchdog, hysteresis, TTT, kanal, anten, beamforming ve hareket degismedi.

Analiz bu kosuyu **CAUSAL_EXPERIMENT** diye etiketler; normal D2 PASS kosusu
gibi sunmaz. Deneyin dar zaman/RNTI guard'i yalniz kayitli seed/run 1/1 ve
2 dBm baseline icin kullanilir. Uretim/regresyon profilinde deney kapali.

## Uygulanan en kucuk senaryo duzeltmesi

D2 helper kurulumuna `SetUePhyAttribute("TxPower", DoubleValue(ueTxPower))`
eklendi; D2 CLI/runner varsayilani **23 dBm**, tum bes UE icin ayni. Factory
ayari D2 helper instance'ina aittir; global Config::SetDefault veya native
sinif varsayilani degistirilmedi. D1'e etkisi yoktur. Tarihsel profil
`--ueTxPower=2` / runner `--ue-tx-power=2` ile yeniden secilebilir.

23 dBm rastgele bir arama sonucunda secilmedi. Mevcut NR orneklerinde acik UE
profili olarak kullaniliyor: `contrib/nr/examples/gsoc-nr-channel-models.cc:108`,
`contrib/nr/examples/gsoc-nr-channel-models.cc:201`.
Bu standart/cihaz uygunluk iddiasi veya paper-parametre replikasyonu degildir;
projenin acik ve izlenebilir radyo-butcesi secimidir. Eski 2 dBm kosulu
hatali native fizik diye yeniden etiketlenmedi.

Yeni `radio_profile.json` guc/UL-PC/deney modunu kaydeder ve analiz input
hash'lerine katilir. Bes UE'nin etkin TxPower CSV degerleri profile karsi
kontrol edilir; kaynak `explicit` ile `library_default` ayrilir. Pasif tanilama
`--diagnoseJoining=1` ile acilir, `diagnostics/timeline.csv` altinda kalir;
mevcut 19 raw CSV semasi degismedi. Yeni header'a da ihtiyac vardir:
`dt-d2-simulation.cc`, `dt-d2-support.h`, `dt-d2-observers.h`,
`dt-d2-diagnostics.h` birlikte scratch'a kopyalanmalidir.

Hysteresis 1.5 dB, TTT 128 ms, joining timeout 200 ms ayni. RRC'ye sahte
EndOk eklenmedi; failure trace veya context cleanup bastirilmadi. UPC kapali
kaldi. Duzeltme, **degisen bir guc profili** altindadir; esit radyo kosullarinda
bir policy performans kazanci olarak yorumlanamaz.

## Regresyon sonuclari

Her kosu 90 s, seed tablodaki gibi, run=1; ayni 3 gNB/5 UE/hareket/UDP/A3.
Normal profil: tum UE'ler 23 dBm, probe kapali. Cevrimdisi kontroller orijinal
D2 schema/kimlik/HO/PRB/candidate/QoS kontrollerini gevsetmeden uygulandi.

| Profil / seed | Producer | Offline | Iki-tarafli HO | Native failure | Eksik target context / pending gNB |
|---|---:|---|---:|---:|---|
|23 dBm, 1 (A)|0|PASS (tekrar karsilastirmasi)|19|0|0 / 0|
|23 dBm, 1 (B)|0|A ile ayni|19|0|0 / 0|
|23 dBm, 2|0|VALIDATED_SINGLE_RUN|5|0|0 / 0|
|23 dBm, 3|0|VALIDATED_SINGLE_RUN|12|0|0 / 0|

Seed1 A/B'nin 19 raw CSV'si ve radio_profile.json'i byte-identical; source,
binary ve shared-library run manifestleri kontrol edildi. Tum UE'lerde
iki komsu olcumleri ve cell-attributed QoS/PRB muhasebesi dogrulandi.
Packet kayiplari suruyor; handover nedeni diye genellenmedi. Ornegin seed1'de
44,000 TX / 41,826 RX var. 2 dBm baseline'da 38,622 RX olmasi, bu calismanin
esit-kosullu handover policy karsilastirmasi oldugu anlamina gelmez.

- Orijinal **69 Python testi** yeniden gecti; 8 yeni proof/profile corruption testi ile **77/77 PASS**. Son kampanyada entegrasyon fixture'i corrected full-a kosusudur.
- `build/utils/ns3.48-test-runner --suite=nr-handover-target --fullness=QUICK --verbose`: native QUICK suite yeniden calistirildi ve iki alt testiyle PASS. Wrapper metadata uyusmazligi icin PHASE_D2_PREPARATION.md dosyasina bakin.
- Yeni 45 s D1 sim ve offline validator PASS. D1'in **12 CSV'si release ile byte-identical**; 49 korunan dosya ve ns-3/standalone Git indexleri degismedi.
- Native model kaynaklarinda degisiklik yok; D2 kaynak/analiz/tanilama ve bu rapor eklendi/guncellendi. Commit/push/stage yapilmadi.
- Son yalniz-Doxygen parameter aciklamasi duzeltmesinden sonra tekrar derlendi; executable hash'i dort tam regresyonda kullanilan binary ile birebir ayni. Test edilen kaynaklar evidence dizininde arsivlendi.

Bu duzeltilmis profil icin joining problemi gorulmedi. Bu sonucun kapsami uc
seed ile sinirlidir; tam hata/recovery kapsami, tum kanal ayristirmasi veya
D2'nin diger roadmap maddeleri tamamlandi iddiasi yoktur. **D2 overall complete
olarak isaretlenmedi.** Orijinal basarisiz deneyler ve onceki validation JSON'i
historical evidence olarak korundu.

## Yeniden uretim ve evidence dosyalari

Asagidaki komutlari ns-3 root'unda ve HER SEFERINDE yeni output yollarinda
ayri ayri calistirin. Tarihsel failure komutu 1, diagnostic analysis 2 dondurur;
bunlar beklenen basarisizlik kodlaridir. No-build binary once derlenmelidir.

```bash
./ns3 build dt-d2-simulation -j 1
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=2 --diagnose-joining --output-dir=dt-output/joining-old-new
.venv-analysis/bin/python -B analysis/phase_d2.py --diagnostic --run-dir=dt-output/joining-old-new --output-dir=dt-output/joining-old-report-new
.venv-analysis/bin/python -B analysis/phase_d2_joining.py --run-dir=dt-output/joining-old-new --output=joining-proof-new.json
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=2 --diagnose-joining --joining-power-probe --output-dir=dt-output/joining-probe-new
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=23 --seed=1 --output-dir=dt-output/joining-fixed-a-new
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=23 --seed=1 --output-dir=dt-output/joining-fixed-b-new
.venv-analysis/bin/python -B analysis/phase_d2.py --run-dir=dt-output/joining-fixed-a-new --compare-run=dt-output/joining-fixed-b-new --output-dir=dt-output/joining-fixed-report-new
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=23 --seed=2 --output-dir=dt-output/joining-seed2-new
.venv-analysis/bin/python -B analysis/run_d2.py --ue-tx-power=23 --seed=3 --output-dir=dt-output/joining-seed3-new
D2_RUN_DIR=dt-output/joining-fixed-a-new .venv-analysis/bin/python -B -m unittest discover -s analysis -p 'test_phase_*.py'
```

Standalone runner icin `--ns3-root=/absolute/path/to/ns-3` verin.
Eski `PHASE_D2_VALIDATION.json` 2 dBm historical baseline'dir. Guncel makine
raporu `docs/PHASE_D2_JOINING_VALIDATION.json`; ham timeline'lar ve profiller ns-3
`dt-output/d2-joining-*` altinda, koruma/test/build/causal proof kayitlari
`research-backups/d2-joining-investigation/` altindadir. Raw evidence overwrite
edilmedi. Tam timeline sirasi sequence + exact time_ns ile korunur.

## Publication note

External C++ file/line references above are relative to the compatible ns-3 checkout. The source report remains unchanged in the local evidence archive. Historical PASS claims and current revalidation are distinguished in PHASE_D2_PREPARATION.md. No native protocol or PHY implementation was fixed; the normal D2 scenario now selects an explicit 23 dBm UE profile.
