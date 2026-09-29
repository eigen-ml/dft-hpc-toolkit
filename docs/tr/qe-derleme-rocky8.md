# Quantum ESPRESSO 7.4.1 Derleme Kılavuzu (Rocky Linux 8)

Hazırlayan: Ata Berk Öztürk · İlk sürüm: 18.07.2025 · Düzenlenmiş sürüm: 2026

Bu kılavuz, Quantum ESPRESSO (QE) 7.4.1 sürümünün Rocky Linux 8.10 üzerinde GNU derleyicileri ve Open MPI ile kaynak koddan derlenmesini anlatmaktadır. Adımlar 2025 yazında bir HPC stajı sırasında sanal makine üzerinde uygulanmış, karşılaşılan hatalar ve çözümleri son bölümde toplanmıştır. İngilizce özeti: [qe-build-rocky8.md](../qe-build-rocky8.md).

Resmî belgeler: <https://www.quantum-espresso.org/Doc/user_guide/>

## 1. Donanım ve sistem

| | |
| --- | --- |
| Platform | Proxmox / QEMU sanal makinesi (Standard PC Q35 + ICH9) |
| İşlemci | Intel Xeon E5-2697 v2, 2,70 GHz, 8 çekirdek |
| Bellek | 32 GB (ilk denemelerde 8 GB) |
| İşletim sistemi | Rocky Linux 8.10 (Green Obsidian) |
| Paket yöneticisi | `dnf` (`apt` yerine) |

Sürüm bilgisi `cat /etc/os-release`, işlemci bilgisi `lscpu` komutuyla görülebilir. Paralel derlemeden önce işlemcinin AVX desteği kontrol edilmelidir (`lscpu | grep -o avx`); bkz. Bölüm 6.

## 2. Gerekli kütüphane ve derleyiciler

| Paket | Görevi |
| --- | --- |
| `gcc`, `gcc-c++`, `gcc-gfortran` | C, C++ ve Fortran derleyicileri. QE büyük ölçüde Fortran ile yazıldığından `gfortran` zorunludur. |
| `openmpi`, `openmpi-devel` | MPI ile paralel çalışma; `mpicc`, `mpif90` sarmalayıcılarını sağlar. |
| `openblas-devel` veya `blas-devel`, `lapack-devel` | Doğrusal cebir (matris çarpımı, özdeğer çözümü). |
| `fftw-devel` | Hızlı Fourier dönüşümü. |
| `scalapack-openmpi-devel` | Dağıtık (paralel) doğrusal cebir. |
| `make`, `cmake` | Derleme araçları. Bu kılavuzda `make` kullanılmaktadır. |
| `libxc`, `hdf5`, `hdf5-openmpi-devel` | İsteğe bağlı: ek değiş-tokuş korelasyon fonksiyonelleri ve HDF5 çıktı desteği. |

Kurulum:

```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y gcc-c++ gcc-gfortran make cmake wget \
    openmpi openmpi-devel openblas-devel lapack-devel fftw-devel \
    scalapack-openmpi-devel
```

Depoda aynı adla bulunmayan paketler `dnf search <paket>` ile aranmalı, uygun varyant (ör. farklı adlandırılmış bir OpenBLAS paketi) kurulmalıdır. Kurulu olup olmadığı `rpm -q <paket>` ile denetlenir.

Rocky Linux'ta Open MPI varsayılan yola eklenmez. Derlemeden önce ortam değişkenleri tanımlanmalıdır:

```bash
export PATH=/usr/lib64/openmpi/bin:$PATH
export LD_LIBRARY_PATH=/usr/lib64/openmpi/lib:$LD_LIBRARY_PATH
which mpif90      # /usr/lib64/openmpi/bin/mpif90 göstermelidir
```

Bu tanımların `~/.bashrc` dosyasına eklenmesi önerilmez; ayrı bir dosyada tutulup derleme öncesinde `source` ile yüklenmesi daha güvenlidir. Denemeler sırasında `.bashrc` içinde biriken eski tanımlar bir derlemenin başarısız olmasına yol açmıştır.

Kurulum için `root` yetkisine sahip bir hesap (programın `/opt` altına kurulması için) ve testlerin yürütüleceği ayrı bir kullanıcı hesabı gereklidir.

## 3. Kaynak kodun indirilmesi

```bash
export LC_ALL=C
cd /opt/src         # ya da derleme için seçilen başka bir dizin
wget https://gitlab.com/QEF/q-e/-/archive/qe-7.4.1/q-e-qe-7.4.1.tar.gz
tar -xzf q-e-qe-7.4.1.tar.gz
cd q-e-qe-7.4.1
```

`LC_ALL=C` tanımı, derleme betiklerinin çıktılarının İngilizce ve standart biçimde olmasını sağlar.

## 4. Yapılandırma (configure)

Çoğu sistem için aşağıdaki komut yeterlidir:

```bash
./configure --enable-parallel --prefix=/opt/qe-7.4.1
```

Sık kullanılan seçenekler:

| Seçenek | Anlamı |
| --- | --- |
| `--enable-parallel` | MPI ile paralel derleme (varsayılan: mümkünse evet) |
| `--enable-openmp` | OpenMP desteği (varsayılan: hayır) |
| `--prefix=<dizin>` | `make install` ile dosyaların kopyalanacağı dizin |
| `--enable-static` | Statik çalıştırılabilir dosyalar (daha büyük ama taşınabilir) |
| `--enable-debug` | Hata ayıklama bayrakları |

Yapılandırma başarılı olduğunda çıktının sonunda bulunan kütüphaneler listelenir. Bu sistemde elde edilen çıktı:

```text
BLAS_LIBS= -lopenblas
LAPACK_LIBS= -lopenblas
SCALAPACK_LIBS=-lscalapack
FFT_LIBS= -lfftw3
```

Kütüphane seçiminin elle verilmesi (`--with-blas=...` vb.) mümkündür, ancak otomatik algılama doğru çalışıyorsa önerilmez. Yapılandırma hatalı sonuçlandığında yeniden denemeden önce `make distclean` ile önceki `make.inc` dosyası temizlenmelidir.

## 5. Derleme, kurulum ve test

```bash
make -j"$(nproc)" all
sudo make install
ls /opt/qe-7.4.1/bin/pw.x
```

Derleme bu sistemde yaklaşık beş dakika sürmüştür. `make clean` yapılandırmayı korur; `make veryclean` veya `make distclean` yapılandırmayı da siler.

Testler `root` olmayan kullanıcıyla yürütülmelidir:

```bash
su - kullanici
cd <kaynak_dizini>/test-suite
make run-tests                 # seri
make run-tests NPROCS=2        # MPI derlemesinin kontrolü
```

Başarısız bir test, ilgili klasörde `test.out.*` ve `test.err.*` dosyaları bırakır (ör. `test-suite/pw_atom/`). Tek bir girdinin elle çalıştırılması:

```bash
mkdir -p ~/espresso && cp test-suite/pw_atom/atom.in ~/espresso/
cp -r pseudo ~/espresso/
cd ~/espresso
mpirun -np 2 /opt/qe-7.4.1/bin/pw.x -in atom.in > atom.out
```

Pseudopotansiyel dosyaları bulunamazsa girdi dosyasının `&CONTROL` bölümüne `pseudo_dir = '/home/kullanici/espresso/pseudo'` satırı eklenmelidir.

## 6. Karşılaşılan hatalar ve çözümleri

Önce Bölüm 2'deki ortam değişkenlerinin doğru yüklendiği kontrol edilmelidir. Oturum kapatılıp yeniden açıldığında `export` ile yapılan tanımlar sıfırlanır.

**`Illegal instruction` (paralel çalıştırmada).** Sanal makineye aktarılan işlemcide AVX desteği yoktu; OpenBLAS ise AVX varsayıyordu. Yalnızca `NPROCS=1` ile çalışılabildi. OpenBLAS kaynak koddan bu işlemciye göre derlendi; sanal makinenin işlemci ayarlarında AVX etkinleştirildikten sonra paralel çalışma da sorunsuz hale geldi.

**`SIGNAL 9 (Killed)` (büyük hesaplarda).** Bellek yetersizliği. `htop` ile doğrulandı; sanal makinenin belleği 8 GB'tan 32 GB'a çıkarıldı. Uzun hesaplar SSH bağlantısı kopsa da sürmesi için `tmux` içinde başlatıldı.

**`PSM3 can't open nic unit` / `fi_endpoint` hataları.** InfiniBand veya Omni-Path kartı bulunmayan tek makinede Open MPI yanlış iletim katmanını seçmektedir. TCP'ye zorlamak sorunu gidermiştir:

```bash
export OMPI_MCA_pml=ob1
export OMPI_MCA_btl=self,tcp
```

**`mpirun has detected an attempt to run as root`.** Hesap ve testler `root` ile yürütülmemelidir. Kullanıcıya test klasörünün sahipliği verilmeli (`sudo chown -R kullanici:kullanici <kaynak_dizini>/test-suite`) ya da girdiler ev dizinine kopyalanmalıdır.

**`undefined reference to dgemm_` (yapılandırma sırasında).** `configure`, Intel MKL yollarını bulmuş ancak MKL ortamı yüklenmemiştir. MKL kullanılacaksa `source /opt/intel/oneapi/setvars.sh` ile ortam yüklenmeli, kullanılmayacaksa MKL yolları ortamdan çıkarılıp OpenBLAS ile yapılandırılmalıdır.

**`undefined reference` (derleme sırasında).** Eksik kütüphane. Bölüm 2'deki paketler kontrol edilmeli, ardından `make distclean` ile temizlenip yeniden yapılandırılmalıdır. GitHub'dan elle derlenen kütüphaneler sistemle uyumsuz olabilir; mümkünse `dnf` deposundaki sürüm tercih edilmelidir.

**`pw.x: command not found`.** Kurulum dizini `PATH` içinde değildir: `export PATH=/opt/qe-7.4.1/bin:$PATH` ya da tam yol kullanılmalıdır.

**`Permission denied`.** Çalıştırılabilir dosyaya veya çalışma dizinine erişim yetkisi yoktur. `chown` ile ilgili kullanıcıya yetki verilmelidir; `sudo` ile çalıştırmak son çare olarak düşünülmelidir.

## 7. Özet

```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y gcc-c++ gcc-gfortran make wget openmpi openmpi-devel \
    openblas-devel lapack-devel fftw-devel scalapack-openmpi-devel
export PATH=/usr/lib64/openmpi/bin:$PATH LD_LIBRARY_PATH=/usr/lib64/openmpi/lib:$LD_LIBRARY_PATH LC_ALL=C
wget https://gitlab.com/QEF/q-e/-/archive/qe-7.4.1/q-e-qe-7.4.1.tar.gz && tar -xzf q-e-qe-7.4.1.tar.gz
cd q-e-qe-7.4.1
./configure --enable-parallel --prefix=/opt/qe-7.4.1
make -j"$(nproc)" all && sudo make install
cd test-suite && make run-tests NPROCS=2     # root olmayan kullanıcıyla
```
