# LEO Satcom Sim

GNU Radio 3.10+ tabanlı bu proje, alçak Dünya yörüngesindeki (LEO) bir uydu
haberleşme bağlantısını uçtan uca simüle etmeyi amaçlar. Verici, yörünge/uzay
kanalı ve alıcı zincirleri modüler tutulacak; BER, EVM ve kodlama kazancı gibi
ölçütler tekrarlanabilir deneylerle incelenecektir. Ortak simülasyon değerleri
`config/params.py` dosyasından yönetilir.

## Fazlar

- **Faz 0 — İskelet ve ortam:** Proje yapısı, ortak parametreler, bağımlılıklar ve smoke test.
- **Faz 1 — LEO kanal modeli:** Yol kaybı, zamanla değişen Doppler, faz gürültüsü, scintillation ve AWGN.
- **Faz 2 — Verici zinciri:** Çerçeveleme, preamble, LDPC kodlama, modülasyon ve RRC darbe şekillendirme.
- **Faz 3 — Alıcı zinciri:** AGC, taşıyıcı/zamanlama eşzamanlama, eşleşmiş filtre ve demodülasyon.
- **Faz 4 — Kod çözme ve paketleme:** Preamble algılama, çerçeve çıkarımı, LDPC çözme ve bit doğrulama.
- **Faz 5 — Performans analizi:** Eb/N0 taraması, BER/EVM ölçümü, kodlama kazancı ve otomatik regresyon testleri.
- **Faz 6 — Doğrulama ve karşılaştırma:** Sonuçların literatürle karşılaştırılması, senaryo kayıtları ve nihai raporlama.

## Ortam kurulumu

GNU Radio için önerilen yol, conda-forge paketlerini kullanan Conda/Mamba
ortamıdır:

```console
conda env create -f environment.yml
conda activate leo-satcom-sim
```

`requirements.txt`, bağımlılıkların araçlar tarafından okunabilen kısa
listesidir. GNU Radio'nun platforma özgü kurulum gereksinimleri nedeniyle tam
ortam kurulumu için `environment.yml` tercih edilmelidir.

## Smoke test

Komutları proje kökünde çalıştırın:

```console
python -m unittest discover -s tests -p "test_*.py" -v
```

Test, GNU Radio 3.10+ importunu ve `config/params.py` ortak parametrelerini
doğrular.

## LEO kanal modeli

`channel/leo_channel_model.py`, tek `complex64` giriş ve çıkışlı bir GNU Radio
`hier_block2` bloğudur. Kompleks örneklerde `abs(x)²` değerinin watt olduğu
kabul edilir ve etkiler aşağıdaki sırada uygulanır:

- `path_loss_db`: Statik serbest uzay güç kaybı; kompleks genlik `10^(-L/20)` ile ölçeklenir.
- `doppler_max_hz`, `doppler_profile`: Doppler, geçiş boyunca `+f_max` değerinden `-f_max` değerine lineer veya parabolik kayar.
- `doppler_pass_duration_s`: Doppler profilinin baştan sona ilerlediği benzetim süresi.
- `phase_noise_std`: Örnek başına random-walk faz artımının radyan cinsinden standart sapmasıdır; `0` etkiyi kapatır.
- `scintillation_std_db`: Yavaş log-normal genlik değişiminin dB standart sapmasıdır; `0` etkiyi kapatır.
- `scintillation_cutoff_hz`: Scintillation sürecinin birinci dereceden alçak geçiren bant genişliğidir.
- `t_sys_kelvin`, `signal_bandwidth_hz`: Kompleks AWGN gücünü `k·T_sys·B` olarak belirler; iki değerden birinin `0` olması AWGN'yi kapatır.
- `random_seed`: Faz gürültüsü, scintillation ve AWGN deneylerini tekrarlanabilir yapar.

Varsayılanlar `config/params.py` içindedir. Yalnızca belirli bir etkiyi test
etmek için diğer etkilerin kayıp/sapma/maksimum değerlerini `0` yapabilirsiniz.

Görsel Doppler ve faz gürültüsü kontrolü için GRC akışını proje kökünden açın:

```console
gnuradio-companion channel/test_channel_standalone.grc
```

Akış, sabit kompleks CW kaynağını kanal modelinden geçirerek QT GUI Frequency
Sink ve QT GUI Time Sink üzerinde gösterir.

## Faz 2 verici zinciri

`tx/tx_chain.py`, byte başına bir bit taşıyan 64-bit payload bloklarını kabul
eden ve `complex64` RRC örnekleri üreten yeniden kullanılabilir bir GNU Radio
`hier_block2` bloğudur. `generate_tx_samples()` yardımcısı aynı zinciri sonlu
payload'larla parametrik taramalarda tekrar çalıştırır.

İşlem sırası şöyledir:

1. **LDPC:** Her 64-bit payload, `fec.ldpc_encoder_make` ve FEC Extended Encoder ile 128-bit codeword'a çevrilir.
2. **Çerçeveleme:** Codeword önüne PN63 preamble, sonuna bir sıfır pad biti eklenir: `63 + 128 + 1 = 192` bit.
3. **Dibit paketleme:** 192 bit, 96 adet QPSK sembol indeksine paketlenir.
4. **Pre-differential eşleme:** `digital.constellation_qpsk()` nesnesinin Gray etiketleri faz-artımı indekslerine dönüştürülür.
5. **Diferansiyel kodlama:** Mod-4 fark kodlaması, sonraki alıcı Costas loop'unun `0/90/180/270°` mutlak faz belirsizliğini kaldırır.
6. **QPSK eşleme:** Diferansiyel indeksler GNU Radio'nun birim güçlü Gray-QPSK noktalarına eşlenir.
7. **RRC:** `sps=4`, `rolloff=0.35` ve 45 tap ile interpolating FIR darbe şekillendirme uygulanır.

Preamble, LDPC'den **sonra** eklenir. Aksi halde LDPC encoder'ın tam 64-bit
giriş sözleşmesi bozulur ve preamble da codeword içinde korunmasız bir frame
işareti olmaktan çıkar. Diferansiyel kodlama bit akışında değil, QPSK
pre-differential eşlemesinden sonra mod-4 sembol indekslerinde yapılır; bu sıra
GNU Radio'nun generic modülatör mimarisiyle aynıdır.

### LDPC matrisi

`data/ldpc_128_64_regular.alist`, seed `131003` ile üretilmiş tam-rank
`H(64×128)` matrisidir. Her değişken düğümün derecesi 3, her kontrol düğümünün
derecesi 6'dır; dolayısıyla kod oranı `k/n = (128-64)/128 = 1/2` olur. Dosya
[klasik alist biçimini](http://www.inference.org.uk/mackay/codes/alist.html)
kullanır ve şu komutla bit düzeyinde aynı şekilde yeniden üretilebilir:

```console
python data/generate_ldpc_alist.py
```

Bu matris, **CCSDS 131.0-B-3'ün normatif kısa matrisi olarak sunulmaz**;
standartta doğrudan tanımlanmayan `(128,64)` geliştirme boyutu için
karşılaştırılabilir MacKay-tipi `(3,6)`-regular araştırma kodudur. İleride gerçek
CCSDS codeword boyutuna geçildiğinde yalnız alist ve `config/params.py` boyutları
değiştirilecektir. GNU Radio'da alist encoder nesnesi FEC Extended Encoder'a
verilir.

### GRC akışları

Kanal içermeyen ayrıntılı TX zinciri:

```console
gnuradio-companion tx/tx_chain.grc
```

İdeal constellation kontrolü:

```console
gnuradio-companion tx/test_tx_ideal.grc
```

TX çıkışı 4 örnek/sembol RRC dalga biçimi olduğu için dört sembol noktasını
doğru anda gözlemek üzere test akışında yalnız ideal matched-RRC ve tam `÷4`
decimation bulunur. Bu düğüm hem `digital.constellation_decoder_cb` hem QT GUI
Constellation Sink'e bağlıdır. Kanal, gürültü veya senkronizasyon hatası yoktur;
geçici filtre başlangıcından sonra dört net QPSK noktası beklenir.

## Faz 3 senkronizasyon zinciri

`rx/rx_sync_chain.py` aşağıdaki alıcı sırasını yeniden kullanılabilir bir
`hier_block2` içinde uygular:

1. TX ile aynı roll-off ve tap sayısına sahip birim kazançlı matched-RRC filtre,
2. `order=4` QPSK Costas loop,
3. `TED_GARDNER` kullanan ve 4 örnek/sembolden 1 örnek/sembole inen Symbol Sync,
4. QPSK hard-decision,
5. mod-4 differential decoder,
6. inverse pre-differential Gray map ve dibit açma.

Differential decoder, Faz 2'deki differential encoder'ın alıcı karşılığıdır.
Costas loop taşıyıcıyı kilitlese bile QPSK'nın dört olası mutlak fazından
hangisinde olduğunu tek başına belirleyemez. Ardışık sembollerin mod-4 farkını
çözmek bu `0/90/180/270°` belirsizliği bilgi bitlerinden kaldırır.

`analysis/sync_quality.py`, Costas'ın ham detector-error ve radyan cinsinden
phase-düzeltme izlerini ayrı tutar. Cycle slip kararı detector-error üzerinde
değil, birkaç semboldeki sarılmış phase değişimi üzerinde
`cycle_slip_jump_threshold_rad=π/4` eşiğiyle verilir. İlk birkaç frame grafiği
`analysis/results/costas_trace_8db.png` dosyasına yazılır.

`rx_sync_chain_top_block` ve `run_sync_simulation(ebno_db=...)`, TX → LEO kanal
→ RX deneyini dışarıdan verilen Eb/No ile çalıştırır. Normalize QPSK deneyinde
hedef kompleks örnek gürültü gücü `σ² = sps/(2·R·EbNo)` olarak hesaplanır ve Faz 1
kanalının `k·T_sys·B` arayüzüne eşdeğer gürültü sıcaklığı olarak verilir. Bu
değer fiziksel donanım sıcaklığı değil, normalize baseband Eb/No ayarının kanal
modeline dönüştürülmüş karşılığıdır.

### Loop kilidi ve bant genişliği

Costas'ın frequency, phase ve phase-detector-error çıkışları ile Gardner timing
error çıkışı ayrı ayrı gözlenebilir. `analysis/lock_detector.py`, son
`lock_window_size=256` adet 8-örnekli grup ortalamasının varyansını hesaplar.
Bu kısa ortalama, `Es=1` ölçeğinde phase-detector karar gürültüsünü bastırır.
Costas ve timing varyansları `0.05` değerinin altındaysa iki loop birlikte
kilitli kabul edilir; eşikler ve `lock_error_average_span=8`
`config/params.py` içinden değiştirilebilir.

- `costas_loop_bw=0.005`: 6 dB ve 8 kHz Doppler regresyonunda cycle-slip/jitter'ı
  bastırırken yaklaşık 24.5 ms içinde kilitlenir; daha küçük değerler daha temiz
  steady-state fakat daha yavaş Doppler/frekans yakalama verir.
- `timing_loop_bw=0.045`: Gardner loop'un burst başlangıcında daha hızlı zamanlama yakalamasını sağlar; daha büyük değer timing jitter ve gürültü duyarlılığını artırır.

Bu değerler kilitlenme hızı ile kilit sonrası gürültü/jitter arasında başlangıç
kompromisidir; Doppler hızı, burst uzunluğu ve Eb/No taramalarına göre yeniden
ayarlanmalıdır.

GRC görsel testi proje kökünden açılır:

```console
gnuradio-companion rx/rx_sync_chain.grc
```

“Costas Lock Metrics” ekranı frequency/phase/error izlerini, “Gardner Timing
Error” ekranı timing hata izini gösterir. Eğrilerin durağanlaşması ve son-pencere
varyanslarının eşik altına inmesi kilit göstergesidir.

## Faz 4 FEC decode ve EVM analizi

`rx/rx_full_chain.py`, Faz 3 senkronizasyon çıkışını PN63 korelatörlü frame
ayırıcıya bağlar. Preamble ve tek QPSK hizalama biti çıkarıldıktan sonra kalan
codeword, `decoder_type` seçimine göre aşağıdaki yollardan birine gider:

- `decoder_type="uncoded"`: 64 bilgi biti doğrudan PN63 frame içine alınır;
  FEC encoder/decoder kullanılmaz. AWGN teori kalibrasyonunda bu yol, bilinen
  taşıyıcı ve sembol zamanlamasıyla koherent QPSK matched-filter alıcısını
  kullanır; diferansiyel hata yayılımı teorik referansa karıştırılmaz.
- `decoder_type="ldpc"`: Faz 2 ile aynı `data/ldpc_128_64_regular.alist`
  matrisi, GNU Radio'nun sum-product/belief-propagation
  `fec.ldpc_decoder.make` sınıfı ve varsayılan
  `ldpc_max_iterations=50` kullanılır.
- `decoder_type="viterbi"`: Karşılaştırma için rate-1/2, constraint length
  `K=7`, `[79, 109]` polinomlu convolutional encoder/Viterbi decoder kullanılır.

LDPC ve Viterbi seçenekleri aynı 64-bit payload → 128-bit codeword → PN63/DQPSK/RRC
arayüzünü kullanır. `digital.constellation_decoder_cb` ve mod-4 differential
decoder Faz 3 hierarchy'sinde çalışır. PN63 başlangıç konumları, arada kaybolan
sembol/frame'leri BER karşılaştırmasına taşımadan referans frame indeksini korur.
LDPC BP için hard bitler `ldpc_hard_llr_magnitude=3` ile `0 → -3`, `1 → +3`
metriğine çevrilir; Viterbi yolu kendi `±1` ölçeğini korur.

Yeniden kullanılabilir TX/RX bloklarının differential modu varsayılan olarak
açıktır. Buna karşılık AWGN BER/coding-gain koşuları
`performance_differential_coding=False` ile koherent QPSK kullanır; çünkü çizilen
`0.5·erfc(sqrt(Eb/No))` referansı differential kararın hata yayılımını içermez.
İki mod `run_full_simulation(..., differential_coding=True|False)` ile açıkça
karşılaştırılabilir.

`analysis/evm_calc.py`, her senkron sembolü `(±1,±1)/√2` kümesindeki en yakın
noktaya atar ve

```text
EVM_rms(%) = sqrt(mean(|received - ideal|²) / mean(|ideal|²)) × 100
```

formülüyle toplam EVM'i hesaplar. Aynı sonuç nesnesi varsayılan 1000 sembollük
pencere trendini, hata vektörlerini ve dört QPSK noktasının histogramını içerir.

Görsel tam zincir:

```console
gnuradio-companion rx/test_rx_full_chain.grc
```

Akıştaki `decoder_type` değişkeni `"uncoded"`, `"ldpc"` veya `"viterbi"` yapılabilir. QT GUI
Constellation Sink senkron sembolleri, Number Sink ise son 1000 sembolün kayan
RMS EVM yüzdesini gösterir.

Otomatik Faz 4 testleri:

```console
python -m unittest tests.test_fec_evm -v
```

EVM tablosu ile LDPC/Viterbi decode-öncesi ve decode-sonrası BER karşılaştırmasını
üretmek için:

```console
python -m analysis.run_fec_evm_analysis --ebno 0 8 10 --frames 1000
```

Komut `analysis/fec_evm_results.csv` dosyasını gerçek GNU Radio koşu sonuçlarıyla
yeniden yazar. Depodaki dosya yalnız sütun şemasını içerir; sayısal satırlar GNU
Radio bulunmayan bir ortamda uydurma sonuç yazılmaması için önceden doldurulmaz.

### Koherent QPSK faz belirsizligi

Performans kosularinda `performance_differential_coding=False` secildiginde
uncoded, LDPC ve Viterbi yollarinin ucu de ayni aliciyi kullanir. Matched RRC
filtre bilinen sembol zamaninda decimate eder; ardindan gercek bir
`digital.costas_loop_cc(order=4)` tasiyiciyi kilitler. Costas'in kalan
0/90/180/270 derece belirsizligi decoder'dan **once** ortak
`_QPSKPhaseAmbiguityFrameExtractor` tarafindan cozulur. Blok PN63'u dort ters
dibit permutasyonuyla skorlar, en iyi rotasyonu tum frame'e uygular ve ancak
sonra 64/128 bitlik codeword'u uncoded, LDPC veya Viterbi yoluna verir.

Ilk acquisition'dan sonra frame cadence sabit tutulur. Tek bir gurultulu PN63
frame'i codeword silmez; dort skor arasindaki marj yetersizse onceki guvenilir
quadrant korunur. Diferansiyel yeniden-kullanim modu ise mevcut
`diff_encoder_bb` / `diff_decoder_bb` ciftini kullanmaya devam eder.

Dort quadrant ve dusuk-SNR frame-BER kontrolu su komutlarla tekrarlanabilir:

```console
python -m analysis.phase_ambiguity_check --frames 500 --ebno -2 0
python -m unittest tests.test_phase_ambiguity -v
```

## Faz 5 Monte Carlo BER ve coding gain

`analysis/ber_sweep.py`, `config/params.py` içindeki `ebno_sweep_db=-2…10 dB`
noktalarında uncoded, LDPC ve K=7 Viterbi zincirlerini batch'ler halinde tekrar
çalıştırır. Eb/No bilgi biti başına tanımlanır:

```text
Eb = Es / (R · log2(M))
N0 = Es / (R · log2(M) · EbNo)
complex sample noise power = N0 · samp_rate / sym_rate
```

QPSK için `log2(M)=2`; uncoded yolda `R=1`, LDPC/Viterbi yollarında `R=1/2`'dir.
Bu nedenle aynı bilgi-bit Eb/No değerinde rate-1/2 simülasyonunun kanal gürültü
gücü uncoded yolun iki katıdır. Hesaplanan güç, LEO kanalının `k·T_sys·B`
arayüzüne eşdeğer sıcaklık olarak aktarılır.

Kalibrasyon için mapper noktaları ortalama `Es=1` olacak şekilde normalize edilir.
Sonlu taplı TX ve RX RRC filtrelerinin konvolüsyonundaki ana karar örneği kazancı
da tam 1 yapılır. GNU Radio `noise_source_c` genliği toplam kompleks standart
sapma olarak kullanıldığı için bloğa `sqrt(complex_noise_power)` verilir; her I/Q
bileşeninin varyansı bunun yarısıdır. Uncoded teori kontrolü şu komutla yalnız
koherent FEC'siz referans yolunu çalıştırır:

```console
python -m analysis.ber_sweep --quick --ebno 0 4 8 10 --bits 50000 --decoders uncoded
```

Costas acquisition/cycle-slip ve warm-up öncesi-sonrası BER ayrımı:

```console
python -m analysis.sync_quality --ebno 8 --frames 2000 --warmup-ms 24.49
```

Hızlı pipeline kontrolü, nokta başına yaklaşık `10⁴` bilgi biti kullanır:

```console
python -m analysis.ber_sweep --quick
```

Hedef `BER=1e-5` için yaklaşık on hata gözlemeyi amaçlayan tam koşu, nokta başına
en az `min_bits_per_point=1_000_000` bilgi biti kullanır ve uzun sürebilir:

```console
python -m analysis.ber_sweep --full
```

Belirli noktalar veya özel bit sayısı da seçilebilir:

```console
python -m analysis.ber_sweep --quick --ebno 0 4 8 10 --bits 20000
```

Sonuçlar `analysis/results/ber_results.csv` dosyasına yazılır. Ardından coding
gain hesabı ve grafik üretilir:

```console
python -m analysis.coding_gain
```

Bu komut log-BER interpolasyonuyla hedef BER'deki uncoded/LDPC/Viterbi Eb/No
kesişimlerini bulur, `coding_gain = EbNo_uncoded - EbNo_LDPC` değerini
`analysis/results/coding_gain.txt` içine ve yarı-log eğrileri
`analysis/results/ber_curves.png` içine kaydeder. Kesikli teorik uncoded QPSK
eğrisi `0.5·erfc(sqrt(Eb/No))` formülüdür. Simülasyon-teori farkı herhangi bir
pozitif BER noktasında 1 dB'yi aşarsa terminalde senkronizasyon veya Eb/No
ölçekleme uyarısı gösterilir.

Faz 5 hızlı otomatik testleri:

```console
python -m unittest tests.test_ber_sweep -v
```

## Faz 6 literatur ve final rapor

`data/literature_reference.csv`, Liva vd. Figure 1 ile Elkelesh vd.
Figure 5-6 icindeki `(128,64)` `(3,6)-regular` egri noktalarinin gorsel
digitizasyonunu icerir. Makaleler CER/BLER, proje ise BER raporlar. Ayni kod ve
kanal icin CER/BLER >= BER oldugundan, referanslarin gercek BER egrisi gosterilen
CER/BLER egrisinin daha solunda olurdu. Proje BER egrisi zaten sagda oldugu icin
raporlanan dB farklari ayni-metrik farkinin muhafazakar bir **alt siniridir**;
metrik farki hafifletici sebep degildir. H matrisi, BP metrigi ve iterasyon
butcesi birebir ayni olmadigi icin bu yine de bir "ayni kod" dogrulamasi degildir.
`literature_tolerance_db=2.0`, `1e-2...1e-4` waterfall
bolgesindeki medyan Eb/No ofseti icin gevsek bir **sinif-tutarliligi** siniridir.
`1e-5` tail farki ayrica tanisal olarak raporlanir.

```console
python -m analysis.literature_compare
python -m analysis.generate_final_report
```

Ilk komut `analysis/results/literature_comparison.png` ve fark CSV'sini; ikinci
komut tum regresyonlari yeniden calistirip `analysis/results/final_report.md`
dosyasini uretir. Grafikte rate-1/2 icin `Eb/No=0.19 dB` Shannon kapasite
referansi dikey cizgiyle gosterilir.
