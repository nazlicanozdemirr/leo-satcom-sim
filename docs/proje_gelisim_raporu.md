# LEO Satcom Sim — Kronolojik Proje Gelişim ve Hata Ayıklama Raporu

Bu belge, GNU Radio 3.10+ tabanlı LEO uydu haberleşme simülasyonunun Faz 0'dan
Faz 6'ya kadar nasıl geliştiğini; yalnız son durumu değil, başarısız ilk
denemeleri, kök nedenleri ve düzeltmelerin nasıl doğrulandığını anlatır.

## Kanıt kapsamı ve izlenebilirlik

- Satır numaraları bu raporun üretildiği çalışma ağacındaki dosyalara aittir.
- Üst Git deposunda `leo-satcom-sim/` bütünüyle `??` (izlenmeyen) durumdadır;
  `git log --all -- leo-satcom-sim` sonuç döndürmemiştir. Bu yüzden tarihsel
  commit checkout'u ile önce/sonra doğrulaması yapılamamıştır.
- “Mevcut kanıt” olarak kaynak kod, testler ve `analysis/results/` artefaktları;
  “oturum günlüğü” olarak geliştirme sırasında kaydedilen sayısal A/B sonuçları
  kullanılmıştır. Git ile yeniden üretilemeyen tarihsel değerler aşağıda bu
  niteliğiyle belirtilir.
- Proje kodu resmi CCSDS matrisi kullanmaz. `data/generate_ldpc_alist.py:1-6`
  bunu açıkça belirtir; mevcut kod deterministik, tam-rank `(3,6)-regular`
  `(128,64)` araştırma kodudur.

## 1. Faz 0 — Proje iskeleti ve tek parametre kaynağı

### Amaç

TX, kanal, RX ve analiz parçalarının birbirinden ayrıldığı; GNU Radio ortamının
ve ortak parametrelerin otomatik sınanabildiği tekrar üretilebilir bir temel
kurmak.

### Yapılanlar

- `config/params.py:1-113`: örnekleme/sembol hızları, RRC, LDPC, preamble,
  senkronizasyon, kanal ve Monte Carlo parametreleri tek kaynakta toplandı.
- `channel/`, `tx/`, `rx/`, `analysis/`, `data/`, `tests/` dizinleri kuruldu.
- `requirements.txt` ve `environment.yml` ile GNU Radio, NumPy, SciPy,
  Matplotlib ve PyYAML bağımlılıkları tanımlandı.
- `tests/test_environment.py:7-31`, GNU Radio 3.10+ sürümünü ve
  `config.params` importunu doğruladı.

### İlk sonuç

Ortam smoke testi, aynı Python yorumlayıcısında hem GNU Radio hem merkezi
parametre modülünün erişilebilir olduğunu gösterdi.

### Karşılaşılan problem

Windows'taki varsayılan Python kurulumunda GNU Radio bulunmuyordu; GNU Radio
testleri Radioconda yorumlayıcısıyla çalıştırılmak zorundaydı.

### Kök neden analizi

GNU Radio'nun Windows kurulumu platforma özgüdür ve genel `pip` ortamından
bağımsız bir Conda/Radioconda ortamına kurulmuştur.

### Düzeltme

Doğrulama komutlarında `C:\Users\nzlcn\radioconda\python.exe` kullanıldı;
kalıcı kurulum yolu `environment.yml` ve README ortam bölümünde belgelendi.

### Doğrulanmış sonuç

Final regresyonda ortam ve parametre smoke testlerinin ikisi de geçti; genel
sonuç 30/30 testtir.

## 2. Faz 1 — LEO uzay kanal modeli

### Amaç

Tek complex64 giriş/çıkışlı bir `gr.hier_block2` içinde başlıca LEO bağlantı
etkilerini fiziksel parametrelerle birleştirmek.

### Yapılanlar

- `channel/leo_channel_model.py:169-252`: ana hierarchy oluşturuldu.
- `channel/leo_channel_model.py:224`: statik path loss,
  `multiply_const_cc` ile genlik ölçeğine çevrildi.
- `channel/leo_channel_model.py:38-89`: lineer/parabolik zamanla değişen
  Doppler rotatörü yazıldı.
- `channel/leo_channel_model.py:91-122`: örnek-başına random-walk faz gürültüsü
  eklendi.
- `channel/leo_channel_model.py:124-167`: yavaş log-normal scintillation
  süreci eklendi.
- `channel/leo_channel_model.py:18,220-245`: `N0=kT`, bant genişliği ve
  `analog.noise_source_c` üzerinden kompleks AWGN yolu kuruldu.
- `channel/test_channel_standalone.grc`: CW tonunun frekans ve zaman alanında
  gözlenebildiği görsel test akışı oluşturuldu.
- `tests/test_channel_model.py:42-96`: kTB SNR ve FFT tabanlı Doppler profil
  testleri eklendi.

### İlk sonuç

CW spektrumu Doppler ile beklenen yönde kaydı; AWGN ölçümü teorik kTB hesabına
yaklaştı.

### Karşılaşılan problem

Bu fazda kalıcı bir regresyon raporlanmadı. Daha sonra Faz 5 kalibrasyonunda
`noise_source_c` genliğinin I/Q-başına mı yoksa toplam kompleks standart sapma
olarak mı yorumlandığı tekrar denetlendi.

### Kök neden analizi

GNU Radio kompleks Gaussian kaynak genliği, toplam kompleks gürültü gücünün
karekökü olarak ele alınmalıdır; her reel bileşenin varyansı toplamın yarısıdır.

### Düzeltme

Kanal arayüzünde `noise_voltage=sqrt(noise_power_w)` ilişkisi korundu ve Faz 5
teori testiyle uçtan uca doğrulandı.

### Doğrulanmış sonuç

`test_awgn_snr_matches_k_t_b` ile lineer ve parabolik Doppler FFT testi final
regresyonda geçti.

## 3. Faz 2 — PN63, LDPC, diferansiyel QPSK ve RRC verici

### Amaç

64-bit payload'u kodlayıp çerçeveleyen, QPSK'ya eşleyen ve `sps=4` RRC darbe
şekillendirmesi uygulayan parametrik TX hierarchy kurmak.

### Yapılanlar

- `data/generate_ldpc_alist.py:13-73`: seed `131003` ile tam-rank, sütun
  derecesi 3, satır derecesi 6 olan `(128,64)` alist üreticisi yazıldı.
- `data/ldpc_128_64_regular.alist`: GNU Radio encoder/decoder ortak matrisi
  kaydedildi.
- `tx/framing.py:6-18`: PN63 + 128-bit codeword + bir pad biti düzeni tanımlandı.
- `tx/tx_chain.py:96-174`: LDPC encoder, preamble inserter, dibit pack,
  pre-differential map, mod-4 differential encoder, QPSK mapper ve interpolating
  RRC filtresi bağlandı.
- Preamble özellikle LDPC'den **sonra** eklendi (`tx/tx_chain.py:163-171`):
  böylece GNU Radio LDPC encoder'ın tam 64-bit giriş sözleşmesi bozulmadı.
- `tx/tx_chain.grc` ve `tx/test_tx_ideal.grc` görsel akışları oluşturuldu.
- `tests/test_tx_chain.py:47-85`: rank/derece, PN63 korelasyon konumu ve tam
  128-bit encoder çıkışı sınandı.

### İlk sonuç

İdeal kanalda dört QPSK kümesi oluştu; alist testi `(3,6)` düzenliliği ve GF(2)
tam rank koşulunu doğruladı.

### Karşılaşılan problem

İlk tasarım varsayımında GNU Radio QPSK constellation noktalarının doğrudan
`Es=1` olduğu kabul edildi. Bu varsayım Faz 5'te yanlış çıktı.

### Kök neden analizi

Mapper'ın gerçek nokta enerjisi ve sonlu taplı interpolating RRC kazancı,
Eb/No→gürültü dönüşümündeki `Es=1` varsayımıyla açıkça bağlanmamıştı.

### Düzeltme

`tx/tx_chain.py:48-55` içindeki `unit_energy_qpsk_points`, constellation
noktalarını ölçülen ortalama enerjiyle bölerek `Es=1` yaptı. Bu değişikliğin
tam kalibrasyon sonucu Faz 5.1'de verilmiştir.

### Doğrulanmış sonuç

TX testlerinin üçü de geçti; `tests/test_ber_sweep.py:67-87` ayrıca mapper
enerjisinin ve TX+RX karar kazancının tam `1.0` olduğunu sınadı.

## 4. Faz 3 — Matched RRC, Costas, Gardner ve kilit kararı

### Amaç

Doppler/faz/timing bozulmalarından sonra QPSK sembollerini tekrar kazanmak ve
loop kilidini sayısal metriklerle gözlemek.

### Yapılanlar

- `rx/rx_sync_chain.py:117-207`: RX synchronization hierarchy kuruldu.
- `rx/rx_sync_chain.py:160-162`: matched RRC, order-4 Costas ve Gardner
  `symbol_sync_cc` bağlandı.
- `rx/rx_sync_chain.py:179-199`: mod-4 differential decoder ve inverse
  pre-differential Gray map eklendi.
- `analysis/lock_detector.py:20-57`: son pencere varyansı ile çift-loop kilit
  kararı yazıldı.
- `rx/rx_sync_chain.grc`: frequency/phase/detector error ve timing error
  çıkışlarının ayrı sink'lerde izlenmesi sağlandı.
- `tests/test_sync_chain.py:19-76`: sakin tail kilidi, Costas varyans trendi ve
  kaba EVM doğrulandı.

### İlk sonuç

6 dB senaryosunda semboller ideal QPSK kümelerine yaklaştı ve loop hata
izlerinin son bölümü küçüldü.

### Karşılaşılan problem

Costas varyans trendi testi daha sonraki tam regresyonda marjinal/kararsız hale
geldi; ham detector-error varyansı doğrudan kilit kalitesi sanılıyordu.

### Kök neden analizi

Loop bandwidth `0.02`, kısa frame ve gürültü altında fazla jitter geçiriyordu.
Ayrıca tek tek detector-error örneklerinin varyansı, karar gürültüsünü loop
kilidinden ayırmıyordu.

### Düzeltme

`config/params.py:50` ile `costas_loop_bw` `0.02 → 0.005` yapıldı;
`config/params.py:57` ve `analysis/lock_detector.py:20-31` ile sekiz örnekli grup
ortalaması eklendi.

### Doğrulanmış sonuç

Costas ilk/son %10 varyans trendi ve EVM testleri geçti. Daha sonra bağımsız
cycle-slip analizi loop'un gerçek quadrant kilidini ayrıca doğruladı.

## 5. Faz 4 — FEC decode, frame extraction ve EVM

### Amaç

Senkron sembollerden hard karar üretmek, PN63 ile codeword sınırını bulmak,
LDPC/Viterbi seçeneklerini aynı arayüzde çözmek ve EVM'i ölçmek.

### Yapılanlar

- `rx/rx_full_chain.py:77-95`: GNU Radio LDPC BP ve K=7 Viterbi decoder
  nesneleri tanımlandı.
- `rx/rx_full_chain.py:159-254`: PN63 codeword extractor yazıldı.
- `rx/rx_full_chain.py:530-635`: `decoder_type=uncoded|ldpc|viterbi` ortak RX
  hierarchy oluşturuldu.
- `analysis/evm_calc.py:46-101`: en yakın `(±1,±1)/sqrt(2)` noktası, RMS EVM,
  pencere trendi ve dört-küme histogramı eklendi.
- `rx/test_rx_full_chain.grc`: constellation ve EVM görselleştirmesi kuruldu.
- `tests/test_fec_evm.py:33-106`: EVM monotonluğu, küme dengesi ve 8 dB LDPC
  kazancı testleri eklendi.

### İlk sonuç

Yüksek Eb/No'da EVM düştü ve dört sembol kümesi dengeli kaldı. Ancak 8 dB LDPC
kazancı testi tam regresyonda güvenilir değildi.

### Karşılaşılan problem

Frame kayıpları olduğunda RX blokları TX payload'larıyla yalnız dizi sırasına
göre karşılaştırılıyor, bir kayıp sonraki bütün frame'leri yanlış hizalıyordu.
LDPC'ye verilen `±1` hard metrik de sabit kararlar için yetersiz güven taşıyordu.

### Kök neden analizi

İzole decoder testi, aynı alist ve GNU Radio BP decoder'ın çalıştığını gösterdi;
sorun decoder çekirdeği değil, RX frame hizalaması ve decoder giriş metriğiydi.

### Düzeltme

`config/params.py:29` ile hard-LLR büyüklüğü `3.0` yapıldı ve
`rx/rx_full_chain.py:602-630` içinde `0→-3`, `1→+3` dönüşümü uygulandı.
Frame indeksleme önce PN konumlarını koruyacak biçimde, daha sonra koherent
cadence için `rx/rx_full_chain.py:797-808` ile mutlak konuma bağlandı.

### Doğrulanmış sonuç

`tests/test_ldpc_decoder_isolated.py:54-87` oturum çıktısı:
`pre=0.0059277`, `soft_post=0.0018984`, `hard_L3_post=1.5625e-5`.
8 dB tam-zincir LDPC sonrası BER testi ve tüm EVM testleri geçti.

## 6. Faz 5.1 — Eb/No kalibrasyonu ve 22 dB sapmanın giderilmesi

### Amaç

`sigma²=sps/(2·R·EbNo)` ile `N0=Es/(R·log2(M)·EbNo)` yollarının aynı fiziksel
ölçeği verdiğini ve uncoded QPSK'nin teoriyle örtüştüğünü doğrulamak.

### Yapılanlar

- `analysis/ber_sweep.py:47-76`: bilgi-bit Eb/No'dan kompleks örnek gürültü
  gücü dönüşümü merkezi fonksiyona alındı.
- `rx/rx_sync_chain.py:19-50`: aynı dönüşümün RX/kanal sıcaklığı karşılığı
  tanımlandı.
- `tests/test_ber_sweep.py:29-87`: rate-1/2 gücün uncoded gücün iki katı,
  teorik 0 dB değer ve `Es/RRC=1` koşulları sınandı.

### İlk sonuç

Oturum günlüğündeki ilk quick sweep, 0 dB'de `BER≈0.445` ölçerken teorik değer
`≈0.079` idi; yatay sapma tanısı yaklaşık 22 dB olarak kaydedildi.

### Karşılaşılan problem

Dört ayrı ölçek/hizalama kusuru birbirine eklenmişti:

1. QPSK mapper gerçek enerji ölçeği `Es≈4` idi.
2. TX+RX sonlu RRC çiftinin karar örneği kazancı tam 1 değildi.
3. Uncoded teori referansı differential-decoded BER ile karşılaştırılıyordu.
4. Gürültülü tek preamble sonrası frame sınırı kalıcı kayabiliyordu.

### Kök neden analizi

Formül cebirsel olarak doğru olsa da waveform, decoder modu ve frame ölçüm
penceresi formüldeki `Es=1`, koherent QPSK ve sabit frame varsayımlarını
sağlamıyordu. Sorun tek bir `N0` çarpanından ibaret değildi.

### Düzeltme

- Mapper `tx/tx_chain.py:48-55` ile birim enerjiye normalize edildi.
- RX RRC tapları `rx/rx_sync_chain.py:53-72` içinde TX·RX karar kazancı tam 1
  olacak şekilde ölçeklendi.
- Teori referansı için koherent alıcı yolu ayrıldı; bugünkü karşılığı
  `rx/rx_full_chain.py:484-527` ve `config/params.py:64-65` içindedir.
- Frame extractor acquisition sonrası sabit cadence koruyacak hale getirildi;
  güncel koherent uygulama `rx/rx_full_chain.py:325-414` arasındadır.

### Doğrulanmış sonuç

Quick 0/4/8/10 dB kontrolünde teori farkı 0.5 dB altına indi. Final full sweep
sonrasında daha güçlü ölçümle en büyük uncoded teori sapması `0.1135 dB` oldu
(`analysis/results/coding_gain.txt`).

## 7. Faz 5.2 — Costas ve 8 dB LDPC regresyon düzeltmesi

### Amaç

Costas varyans trendi ile LDPC decode-kazancı testlerinin yeni kalibrasyon
sonrasında neden kaldığını ayırmak.

### Yapılanlar

- Costas ilk/son %10 varyansları ham sayılarla incelendi.
- Decoder, gerçek RX'ten bağımsız sentetik-AWGN codeword'larla sınandı.
- Frame extraction ve decoder metriği ayrı A/B değişkenleri olarak ele alındı.

### İlk sonuç

İki test de başarısızdı. Git geçmişi bulunmadığı için “bugünkü değişiklikten
önce” checkout tekrarı yapılamadı; oturum A/B günlüğü Costas testinin önceden de
marjinal olduğunu gösterdi.

### Karşılaşılan problem

Costas fazla geniş bandwidth ile gürültü geçiriyordu. LDPC tarafında ise sağlam
decoder, yanlış eşlenmiş frame dizileri ve düşük güvenli hard metrik yüzünden
tam zincirde beklenen kazancı gösteremiyordu.

### Kök neden analizi

Costas sorunu gerçek loop ayarı/test metriği problemiydi. LDPC sorunu alist veya
`fec.ldpc_decoder.make` çağrısı değil, decoder çevresindeki veri sözleşmesiydi.

### Düzeltme

- `costas_loop_bw: 0.02→0.005`, `lock_error_average_span=8`.
- LDPC hard metriği `±1→±3`.
- Frame kaybı referans indeksine yansıtıldı; koherent nihai çözüm mutlak cadence
  indekslemesidir (`rx/rx_full_chain.py:945-960`).

### Doğrulanmış sonuç

Bu tur sonunda oturum günlüğünde 24/24 test geçti. Sonraki fazlarda eklenen
regresyonlarla güncel toplam 30/30'dur.

## 8. Faz 5.3 — Costas kalite doğrulaması ve differential/koherent ayrımı

### Amaç

8 dB'deki `pre-FEC BER=0.0194` değerinin teori `≈0.0061`'den 3.2 kat büyük
olmasının acquisition geçişi mi, cycle slip mi, yoksa ölçüm modeli mi olduğunu
bulmak.

### Yapılanlar

- `analysis/sync_quality.py:55-92`: birkaç sembolde `π/4` üzeri phase-estimate
  sıçramalarını gruplayan cycle-slip dedektörü yazıldı.
- BER acquisition öncesi/sonrası ve slip'li/slip'siz frame'lere ayrıldı.
- `analysis/results/costas_trace_8db.png` ile ham detector error ve gerçek phase
  estimate izi kaydedildi.
- Aynı senaryo differential açık/kapalı çalıştırıldı.

### İlk sonuç

Yakınsama süresi yaklaşık `24.49 ms / 192 ms` idi; buna rağmen yalnız
yakınsama-sonrası pencere farkı bütünü açıklamadı. 2000 frame içinde cycle slip
bulunmadı. İki ilk hipotez de elendi.

### Karşılaşılan problem

Differential QPSK'nin hata yayılımı, koherent QPSK
`0.5·erfc(sqrt(Eb/No))` teorisiyle karşılaştırılmıştı.

### Kök neden analizi

Bir differential sembol kararı ardışık iki mutlak sembole bağlıdır; tek taşıyıcı
kararı hatası komşu differential kararlara yayılabilir. Bu, Costas loop temiz
kilitli olsa bile koherent teoriye göre BER'i yükseltir.

### Düzeltme

Performans ölçümleri `config/params.py:64` ile
`performance_differential_coding=False` koherent moda geçirildi. Yeniden
kullanılabilir link modu differential kalmaya devam etti.

### Doğrulanmış sonuç

Oturum A/B sonucunda differential kapalı `BER=0.00805`, teori yaklaşık `0.0060`
oldu; fark yaklaşık %34 ile belirlenen implementation-loss bandında kaldı.
Cycle-slip oranı `0/2000`; bu turda 27/27 test geçti.

## 9. Faz 5.4 — Koherent QPSK faz belirsizliği

### Amaç

Order-4 Costas'ın 0/90/180/270° kilit çözümlerini differential coding kapalıyken
her decoder yolunda deterministik biçimde çözmek.

### Yapılanlar

- `rx/rx_full_chain.py:24-32,257-271`: dört inverse dibit rotasyon permütasyonu
  tanımlandı.
- `rx/rx_full_chain.py:274-422`: PN63'ü dört rotasyonda skorlayan
  `_QPSKPhaseAmbiguityFrameExtractor` eklendi.
- `rx/rx_full_chain.py:484-527`: bilinen timing + gerçek order-4 Costas kullanan
  koherent performans alıcısı yazıldı.
- `rx/rx_full_chain.py:565-590`: uncoded/LDPC/Viterbi yolları aynı çözücüye
  bağlandı.
- `analysis/phase_ambiguity_check.py:27-67` ve
  `tests/test_phase_ambiguity.py:22-68` eklendi.

### İlk sonuç

İnceleme, koherent performans yollarında ortak bir ambiguity resolver olmadığını
gösterdi. Uncoded yol Costas'ı bypass ediyor; kodlu yollar Costas çıktısını
doğrudan decoder'a veriyordu.

### Karşılaşılan problem

İlk resolver düşük SNR'de noisy Gardner sembol ekleme/silmeleri ve her frame'i
yeniden preamble eşiğine bağlama nedeniyle özellikle LDPC -2 dB'de yüksek
frame kaybı/yanlış hizalama üretti.

### Kök neden analizi

Full BER senaryosunda timing offset yoktu; buna rağmen Gardner'ın düşük SNR
jitter'ı deterministik frame cadence'i bozuyordu. Ayrıca content/Hamming tabanlı
TX frame araması yüksek BER'de yanlış minimum seçiyordu.

### Düzeltme

- Koherent performans yolu sembol-hızında deterministik RRC decimation kullanıp
  gerçek Costas'ı korudu.
- İlk acquisition sonrası exact frame cadence korundu; düşük PN skorunda frame
  silmek yerine son güvenilir quadrant tutuldu (`rx/rx_full_chain.py:325-405`).
- TX frame indeksi bit içeriğinden değil mutlak PN konumundan üretildi
  (`rx/rx_full_chain.py:797-808`).

### Doğrulanmış sonuç

Zorlanmış dört quadrant, üç decoder yolunun tamamında doğru seçildi. `+π/2`
düşük-SNR kontrolü:

| Eb/No | Yol | Değerlendirilen frame | BER>0.3 | Oran |
|---:|---|---:|---:|---:|
| -2 dB | uncoded | 499 | 0 | %0.00 |
| -2 dB | LDPC | 499 | 6 | %1.20 |
| -2 dB | Viterbi | 499 | 1 | %0.20 |
| 0 dB | uncoded | 499 | 0 | %0.00 |
| 0 dB | LDPC | 499 | 0 | %0.00 |
| 0 dB | Viterbi | 499 | 0 | %0.00 |

En kötü oran %2 sınırının altındadır; güncel regresyon 30/30 geçti.

## 10. Faz 5.5 — Full Monte Carlo sweep ve coding gain

### Amaç

`-2…10 dB` aralığında uncoded, LDPC ve Viterbi BER eğrilerini yeterli bit
sayısıyla ölçmek ve `BER=1e-5` coding gain'i hesaplamak.

### Yapılanlar

- `analysis/ber_sweep.py:79-193`: 500-frame batch'lerle minimum bit hedefine
  kadar Monte Carlo biriktirme ve üç decoder modu.
- `analysis/coding_gain.py:56-93`: log-BER üzerinde hedef kesişim interpolasyonu.
- `analysis/coding_gain.py:95-110`: uncoded teoriye yatay dB sapma kontrolü.
- `analysis/results/ber_results.csv`, `coding_gain.txt` ve `ber_curves.png`
  üretildi.

### İlk sonuç

Full komut başarıyla tamamlandı; 13 nokta × 3 yolun her birinde yaklaşık
1.02 milyon geçerli bilgi biti ölçüldü.

### Karşılaşılan problem

9–10 dB kodlu noktalarda sıfır hata gözlendi. Bu noktalar doğrudan pozitif BER
interpolasyonuna uygun değildi.

### Kök neden analizi

Bir milyon bitte sıfır hata yalnız BER için üst sınır verir. Hedef `1e-5`, LDPC
ve Viterbi için pozitif 7–8 dB noktaları arasında kaldığından kesişim yine
bracket edilebildi.

### Düzeltme

`coding_gain.py`, yalnız pozitif BER örneklerini ve hedefi çevreleyen iki noktayı
log ölçekte kullandı; sıfır noktaları yapay epsilon ile değiştirilmedi.

### Doğrulanmış sonuç

- Uncoded `BER=1e-5`: `9.5121 dB`
- LDPC `BER=1e-5`: `7.6256 dB`
- Viterbi `BER=1e-5`: `7.7187 dB`
- LDPC coding gain: `1.8865 dB`
- Maksimum uncoded teori sapması: `0.1135 dB`

## 11. Faz 6.1 — LDPC matris kapsam kararı

### Amaç

Resmi CCSDS matrisiyle birebir normatif iddia mı kurulacağına, yoksa mevcut kısa
regular kodun aynı parametreli literatür sınıfıyla mı karşılaştırılacağına karar
vermek.

### Yapılanlar

Oturum planında CCSDS AR4JA `k=1024` ve kısa telecommand seçenekleri
değerlendirildi. Mevcut kodun kimliği README ve üretici docstring'inde resmi
CCSDS olmadığı biçiminde netleştirildi (`README.md:94-110`,
`data/generate_ldpc_alist.py:1-6`).

### İlk sonuç

Resmi daha uzun bloklara geçişin yaklaşık 16× bit/frame ve yeniden kalibrasyon,
FEC, sweep ve literatür doğrulama maliyeti getireceği öngörüldü. Bu kararın
commit kaydı yoktur; gerekçe oturum günlüğünden alınmıştır.

### Karşılaşılan problem

Mevcut `(128,64)` matrisi “CCSDS 131.0-B-3 kısa matrisi” diye sunmak teknik
olarak yanlış olacaktı.

### Kök neden analizi

Parametre eşitliği matris kimliği değildir. Seed ile üretilen random regular H,
CCSDS'nin normatif protograph/matris yapısını taşımaz.

### Düzeltme

Normatif CCSDS iddiasından vazgeçildi; karşılaştırma aynı `(n,k,R,dv,dc)`
sınıfıyla sınırlandı.

### Doğrulanmış sonuç

Alist testi mevcut kodun tam-rank `(3,6)-regular (128,64)` olduğunu, kaynak ve
README ise CCSDS olmadığını birlikte doğrular.

## 12. Faz 6.2 — Literatür digitizasyonu ve sınıf karşılaştırması

### Amaç

Mevcut regular kodun waterfall konumunu aynı kısa-blok sınıfındaki yayımlanmış
eğrilerle karşılaştırmak ve asimptotik kapasite referansını göstermek.

### Yapılanlar

- Liva vd. arXiv:1610.00873 Figure 1 ve Elkelesh vd. arXiv:1903.03128
  Figure 5–6 PDF'leri indirildi ve yüksek çözünürlüklü sayfalar incelendi.
- Üç `(3,6)-regular` CER/BLER eğrisi görsel olarak digitize edilip
  `data/literature_reference.csv` içine kaynak/şekil/metric etiketiyle yazıldı.
- `config/params.py:83-86`: sınıf toleransı `2.0 dB`, rate-1/2 Shannon referansı
  `0.19 dB` yapıldı.
- `analysis/literature_compare.py:35-220`: log-error interpolasyonu, fark
  tablosu, waterfall medyanı ve karşılaştırma grafiği üretildi.

### İlk sonuç

Waterfall medyan mutlak ofsetleri:

- Liva Figure 1, 200 BP iterasyonu: `1.453 dB`
- Elkelesh Figure 5, 200 BP iterasyonu: `1.450 dB`
- Elkelesh Figure 6, 20 BP iterasyonu: `1.489 dB`

### Karşılaşılan problem

`1e-4` tekil noktada iki 200-iterasyon referansı yaklaşık `2.01 dB` ile sınırı
çok az aştı; `1e-5` tail farkları yaklaşık `2.54 dB` oldu. 20-iterasyon eğrisi
tail'de `1.943 dB` ile sınır içindeydi.

### Kök neden analizi

Karşılaştırılan H matrisleri ve decoder çalışma koşulları aynı değildir.
Projenin H üreticisi socket shuffle + rank kontrolü yapar
(`data/generate_ldpc_alist.py:38-60`); PEG/girth optimizasyonu yapmaz. Kısa
döngülerin, daha fazla BP iterasyonundan literatürdeki PEG tasarımı kadar fayda
alınmasını engellemesi makul bir açıklamadır, fakat bu projede girth/absorbing
set ölçümü yapılmadığı için kanıtlanmış nedensellik değil bir hipotezdir.

### Düzeltme

Birincil PASS/FAIL ölçütü `1e-2…1e-4` waterfall noktalarının kaynak-başına
medyan mutlak ofseti olarak tanımlandı. `1e-5` ayrı tail tanısı olarak tutuldu;
PASS/FAIL toleransı 2 dB olarak bırakıldı.

### Doğrulanmış sonuç

En kötü waterfall medyanı `1.4889 dB < 2.0 dB`; sınıf-tutarlılığı **PASS**.
Farkların tamamı `analysis/results/literature_difference.csv`, grafik
`analysis/results/literature_comparison.png` içindedir.

## 13. Final rapor metrik-yönü düzeltmesi

### Amaç

Proje BER'i ile literatür CER/BLER'i arasındaki yön ilişkisinin raporda doğru
yorumlanmasını sağlamak.

### Yapılanlar

- `analysis/literature_compare.py` grafik notu düzeltildi.
- `analysis/generate_final_report.py` açıklama, tail yorumu ve sonuç paragrafı
  düzeltildi.
- README Faz 6 bölümü aynı yön bilgisiyle güncellendi.
- `analysis/results/final_report.md` ve literature grafiği yeniden üretildi.

### İlk sonuç

Önceki rapor, BER–CER/BLER metrik farkını tail farkını hafifletebilecek bir
belirsizlik gibi sunuyordu.

### Karşılaşılan problem

Bu yön yanlıştı. Aynı kod/kanal için bir blokta en az bir bit hatası bulunması
blok hatası olduğundan `CER/BLER ≥ BER` olur. Bağımsız bitlerin kaba modeli
`CER≈1-(1-BER)^k` biçimindedir; LDPC hata korelasyonu nedeniyle bu eşitlik kesin
bir dönüşüm değildir.

### Kök neden analizi

Referans CER/BLER eğrisi BER'e dönüştürülse sola, yani daha iyi Eb/No'ya
kayardı. Proje BER eğrisi gösterilen CER/BLER'in zaten sağındaysa, aynı-metrik
BER farkı çizelgedeki farktan daha küçük değil, muhtemelen daha büyüktür.

### Düzeltme

Raporlanan dB farkları “metrik uyuşmazlığı nedeniyle muhafazakâr alt sınır”
olarak yeniden tanımlandı. İsteğe bağlı `k×BER` dönüşümü eklenmedi; korelasyonlu
LDPC hata olaylarında sahte kesinlik üreteceği için ham digitize değerler ve
metrik etiketi korunmuştur.

### Doğrulanmış sonuç

2 dB PASS/FAIL sınıflandırması değişmedi. Açıklama artık metrik farkının sonucu
hafifletmediğini, gerçek BER–BER açığının daha büyük olabileceğini açıkça söyler.

## Öğrenilenler

1. **Normalizasyon varsayımı ölçülmelidir.** Constellation'ın adı “QPSK” olsa da
   `Es=1` garanti değildir; interpolator ve matched filtre kazancı birlikte karar
   örneğinde ölçülmelidir.
2. **Eşdeğer cebir, eşdeğer implementasyon demek değildir.** İki Eb/No formülü
   aynı olsa bile PSD convention, kompleks/IQ varyansı, sample/symbol oranı ve
   filtre kazancı uçtan uca sınanmalıdır.
3. **Teoriyle aynı karar modeli kullanılmalıdır.** Differential QPSK BER'i
   koherent QPSK teorisine doğrudan bağlamak, gerçek loop problemi olmayan bir
   implementation loss üretir.
4. **Ham loop error tek başına kilit kanıtı değildir.** Detector-error jitter,
   phase estimate cycle slip ve acquisition geçişi ayrı ölçülmelidir.
5. **Frame kaybı içerik hizalamasıyla gizlenmemelidir.** Yüksek BER'de Hamming
   minimumu yanlış TX frame'i seçebilir; preamble konumu/cadence metadata'sı
   veri boyunca taşınmalıdır.
6. **Paylaşılan alt sistem gerçekten paylaşılmalıdır.** Uncoded, LDPC ve Viterbi
   yollarından biri farklı timing/phase resolver kullanırsa karşılaştırma adil
   değildir. Ortak ambiguity resolver bu sınıf hatayı önledi.
7. **İzole test kök nedeni hızla ayırır.** Sentetik-AWGN LDPC testi, alist/BP
   çekirdeğini frame extraction ve metrik ölçeklemesinden ayırdı.
8. **BER, CER ve BLER yönü karıştırılmamalıdır.** `CER/BLER≥BER`; proje BER'inin
   referans CER/BLER'in sağında olması ölçülen dB açığını muhafazakâr alt sınır
   yapar, hafifletici sebep yapmaz.
9. **Sıfır hata sıfır BER değildir.** Sonlu Monte Carlo'da güven üst sınırıdır;
   interpolasyon yalnız hedefi çevreleyen pozitif noktalarla yapılmalıdır.
10. **Kod sınıfı kod kimliği değildir.** Aynı `(n,k,dv,dc)` farklı girth,
    trapping/absorbing set ve minimum distance özellikleri gösterebilir. Resmi
    standard iddiası ancak normatif matris ve decoder koşulları eşleşiyorsa
    kurulmalıdır.
11. **Git izlenebilirliği teknik doğrulamanın parçasıdır.** Bu çalışma ağacının
    izlenmemesi tarihsel A/B sonuçlarının commit üzerinden yeniden üretilmesini
    engelledi. Gelecek projede her kalibrasyon kilometre taşı ayrı commit/tag ve
    makine-okunur sonuç dosyasıyla saklanmalıdır.

