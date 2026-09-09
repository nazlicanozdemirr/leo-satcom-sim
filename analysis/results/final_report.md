# LEO Satcom Sim — Faz 0-6 Final Doğrulama Raporu

Üretim zamanı: `2026-09-03T12:16:43+03:00`

## Yönetici özeti

- Tam regresyon: **PASS (30/30 test)**
- Uncoded QPSK teori sapması: **0.1135 dB** (1 dB sınırının altında)
- Hedef BER `1e-5` LDPC coding gain: **1.8865 dB**
- Literatür sınıf-tutarlılığı: **PASS**; en kötü waterfall medyan ofseti **1.4889 dB** / tolerans **2.0 dB**
- Rate-1/2 Shannon kapasite referansı: **0.19 dB Eb/No**

## Faz durumları

| Faz | Durum | Doğrulanan çıktı |
|---:|:---:|---|
| 0 | PASS | Proje iskeleti, merkezi parametreler ve GNU Radio ortam smoke testi |
| 1 | PASS | Yol kaybı, Doppler, faz gürültüsü, scintillation ve kTB tabanlı AWGN kanal modeli |
| 2 | PASS | PN63, (128,64) (3,6)-regular LDPC, QPSK ve birim-enerjili TX RRC zinciri |
| 3 | PASS | Matched RRC, Costas, Gardner ve cycle-slip/senkronizasyon kalite kontrolleri |
| 4 | PASS | Uncoded/LDPC/Viterbi yolları, EVM ve izole LDPC decoder doğrulaması |
| 5 | PASS | 13 noktalı full BER sweep, teori kalibrasyonu ve coding-gain analizi |
| 6 | PASS | İki makaleden görsel digitizasyon, sınıf-tutarlılığı grafiği ve final rapor |

## Faz 5 kalibrasyon ve coding gain

QPSK mapper ve TX+RX RRC karar örneği `Es=1` olacak şekilde normalize edilmiştir. Full sweep içindeki uncoded eğrinin `0.5·erfc(sqrt(Eb/No))` teorisine en büyük yatay sapması `0.1135 dB` olmuştur.

- Uncoded `BER=1e-5`: `9.5121 dB`
- LDPC `BER=1e-5`: `7.6256 dB`
- Viterbi `BER=1e-5`: `7.7187 dB`
- LDPC coding gain: `1.8865 dB`

| Eb/No (dB) | Uncoded BER | LDPC BER | Viterbi BER | Bits |
|---:|---:|---:|---:|---:|
| -2 | 0.131439 | 0.250656 | 0.479257 | 1,019,904 |
| -1 | 0.104599 | 0.205036 | 0.453778 | 1,019,904 |
| 0 | 0.079491 | 0.173772 | 0.395544 | 1,019,904 |
| 1 | 0.0567933 | 0.13682 | 0.287828 | 1,019,904 |
| 2 | 0.0382875 | 0.091197 | 0.15689 | 1,019,904 |
| 3 | 0.0233592 | 0.043595 | 0.0568916 | 1,019,904 |
| 4 | 0.0127061 | 0.0131601 | 0.0131257 | 1,019,904 |
| 5 | 0.00613336 | 0.00232496 | 0.00259926 | 1,019,904 |
| 6 | 0.00256861 | 0.000236802 | 0.000488281 | 1,019,904 |
| 7 | 0.00074661 | 4.79475e-05 | 6.17705e-05 | 1,019,904 |
| 8 | 0.000207446 | 3.91408e-06 | 4.90242e-06 | 1,019,904 |
| 9 | 3.62052e-05 | 0 | 0 | 1,019,904 |
| 10 | 2.93556e-06 | 0 | 0 | 1,019,904 |

## Faz 6 literatür karşılaştırması

Referanslar [Liva vd., Figure 1](https://arxiv.org/pdf/1610.00873) ile [Elkelesh vd., Figure 5–6](https://arxiv.org/pdf/1903.03128) grafiklerinden görsel olarak digitize edilmiştir. Referanslar CER/BLER, proje ise BER raporlar. Aynı kod ve kanal için CER/BLER, BER'den büyük veya eşittir; dolayısıyla referansların BER eğrisi gösterilen CER/BLER eğrisinden daha solda olurdu. Proje BER eğrisi zaten sağda olduğundan, tablodaki dB farkları gerçek aynı-metrik farkının muhafazakâr bir alt sınırıdır. H matrisi, BP girdi metriği ve iterasyon bütçesi de aynı olmadığından sonuç matris eşitliği değil, waterfall konumu üzerinden sınıf-tutarlılığı kontrolüdür.

| Referans eğri | Waterfall medyan | 1e-5 tail farkı |
|---|---:|---:|
| Liva2016_Fig1_reg36 | 1.453 dB | 2.538 dB |
| Elkelesh2019_Fig5_reg36 | 1.450 dB | 2.538 dB |
| Elkelesh2019_Fig6_reg36 | 1.489 dB | 1.943 dB |

Birincil `1e-2…1e-4` waterfall medyanlarının tamamı `2.0 dB` tolerans içindedir. 200-iterasyonlu referanslarda tekil `1e-4` farkı yaklaşık `2.01 dB`, `1e-5` tail farkı yaklaşık `2.54 dB` olmuştur. Tail sonucu yalnız dört simülasyon hatasına dayanan `8 dB` noktası nedeniyle istatistiksel olarak tanısal kabul edilmiştir. BER–CER/BLER metrik uyuşmazlığı bu farkı hafifletmez; tersine aynı-metrik BER farkının daha büyük olması beklenir.

## Çıktılar

- `analysis/results/ber_results.csv`
- `analysis/results/ber_curves.png`
- `analysis/results/coding_gain.txt`
- `data/literature_reference.csv`
- `analysis/results/literature_difference.csv`
- `analysis/results/literature_comparison.png`
- `analysis/results/final_report.md`

## Sonuç

Proje Faz 0-6 kapsamını tamamlamıştır. Eb/No kalibrasyonu teorik uncoded QPSK ile uyumludur, koherent faz belirsizliği bütün decoder yollarında PN63 ile çözülmektedir ve LDPC yolu hedef BER çevresinde yaklaşık 1.89 dB coding gain sağlamaktadır. Kısa-blok regular-LDPC waterfall konumu seçilen 2 dB sınıf toleransı içinde literatürle tutarlıdır; derin tail bölgesi doğrudan soft-BP CER/BLER eşleşmesi olarak yorumlanmamalıdır. Raporlanan dB farkları, metrik uyuşmazlığı nedeniyle muhafazakâr bir alt sınırdır.
