"""LEO uydu haberleşme simülasyonunun ortak yapılandırma değerleri.

Bu modül; verici, kanal, alıcı ve analiz bileşenlerinin kullanacağı
parametreler için projenin tek doğruluk kaynağıdır. Değerler SI birimlerindedir;
dB ile ifade edilen büyüklüklerin adlarında ayrıca ``_db`` son eki bulunur.
"""

# Örnekleme ve sembol hızları (saniye başına örnek/sembol).
samp_rate = 2_000_000
sym_rate = 500_000

# Sembol başına örnek sayısı; hızların tam sayı oranı olması beklenir.
sps = samp_rate // sym_rate

# Kök yükseltilmiş kosinüs (RRC) darbe şekillendirme parametreleri.
rrc_rolloff = 0.35

# 11 sembollük nominal filtre uzunluğunu tek tap sayısına tamamla (44 -> 45).
_rrc_nominal_ntaps = 11 * sps
rrc_ntaps = _rrc_nominal_ntaps + (1 - _rrc_nominal_ntaps % 2)

# LDPC kod oranı ve geliştirme/debug için kısaltılmış blok boyutları (bit).
ldpc_code_rate = 0.5
ldpc_n_short = 128
ldpc_k_short = 64

# LDPC BP decoder'ın codeword başına azami yineleme ve hard-LLR büyüklüğü.
ldpc_max_iterations = 50
ldpc_hard_llr_magnitude = 3.0

# Karşılaştırma yolundaki standart rate-1/2, K=7 convolutional kodu.
viterbi_constraint_length = 7
viterbi_rate_inverse = 2
viterbi_polynomials = (79, 109)

# Çerçeve algılama ve senkronizasyon için PN preamble uzunluğu (bit).
preamble_len = 63

# x^6 + x + 1 ilkel polinomu, all-ones başlangıcı ile üretilen PN63 m-sequence.
preamble_polynomial = "x^6 + x + 1"
preamble_bits = tuple(
    int(bit)
    for bit in "111111010101100110111011010010011100010111100101000110000100000"
)

# 63-bit preamble + 128-bit codeword'u QPSK dibit sınırına tamamlayan pad biti.
frame_pad_bits = 1

# Taşıyıcı ve sembol zamanlama döngülerinin normalize bant genişlikleri.
costas_loop_bw = 0.005
timing_loop_bw = 0.045

# Senkronizasyon kilidi için son pencere hata varyansı eşikleri.
costas_lock_var_threshold = 0.05
timing_lock_var_threshold = 0.05
lock_window_size = 256
lock_error_average_span = 8

# Costas phase düzeltmesinde birkaç sembollük ani quadrant sıçraması eşiği.
cycle_slip_jump_threshold_rad = 3.141592653589793 / 4.0
cycle_slip_jump_span_symbols = 4

# AWGN BER/coding-gain referansı koherent QPSK teorisiyle karşılaştırılır.
performance_differential_coding = False
performance_costas_loop_bw = 0.0001
phase_resolver_max_preamble_errors = 20
phase_resolver_min_score_margin = 3
phase_resolver_search_radius_bits = 8

# Faz 3 otomatik ideal-QPSK kalite sınırı (RMS en yakın-nokta mesafesi).
sync_evm_threshold = 0.60

# EVM trendinin varsayılan pencere uzunluğu (senkron sembol).
evm_window_symbols = 1_000

# BER analizinde kullanılacak Eb/N0 noktaları: -2 dB ile 10 dB (dahil).
ebno_sweep_db = list(range(-2, 11, 1))

# Simülasyonun ulaşmayı hedeflediği bit hata oranı.
target_ber = 1e-5

# Farkli (3,6)-regular H matrisleri ve BER/CER-BLER metrikleri icin sinif toleransi.
literature_tolerance_db = 2.0

# Rate-1/2 binary-input AWGN kapasite duvari (asimptotik referans, Eb/N0).
shannon_limit_r05_db = 0.19

# Hedef BER noktasında yaklaşık 10 hata gözlemek için asgari bilgi biti sayısı.
min_bits_per_point = 1_000_000

# Hızlı regresyon ve bellek-sınırlı Monte Carlo batch varsayılanları.
quick_bits_per_point = 10_000
monte_carlo_batch_frames = 500

# LEO uzay kanalı için alıcı gürültü ve yayılım varsayılanları.
t_sys_kelvin = 290.0
signal_bandwidth_hz = 500_000.0
phase_noise_std = 1e-4
doppler_max_hz = 40_000.0
doppler_profile = "linear"
scintillation_std_db = 1.0
path_loss_db = 150.0

# Zamanla değişen kanal süreçlerinin karakteristik zaman sabitleri.
doppler_pass_duration_s = 10.0
scintillation_cutoff_hz = 2.0

# Tekrarlanabilir kanal benzetimleri için sıfırdan farklı RNG tohumu.
channel_random_seed = 24_301

# Tekrarlanabilir TX payload ve LDPC matris üretimi tohumları.
tx_random_seed = 20_260_902
ldpc_matrix_seed = 131_003
