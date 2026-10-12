# Хамаарлын нийцэл ба баталгаажуулах үндэслэл

Шалгасан өдөр: 2026-10-06 (Asia/Seoul). Доорх хүснэгт нь сонголт хийх лавлагаа; холбогдсон төхөөрөмжийн OS/ROS-ийг эдгээрээс таамаглан сонгохгүй. `scripts/inspect_jetson.sh`-ийг **Jetson дээр** ажиллуулж бодит үр дүнтэй тулгана.

| Бүрэлдэхүүн | Албан ёсны баримтаар тогтоосон зүйл | Энэ төслийн шийдвэр |
|---|---|---|
| JetPack | JetPack 5.1.5 нь L4T 35.6.1 / Ubuntu 20.04, JetPack 6.2.1 нь L4T 36.4.4 / Ubuntu 22.04 суурьтай. | JetPack нэрнээс бус `/etc/nv_tegra_release`, `/etc/os-release`, package inventory-оос шийдвэр гаргана. Энд upgrade/flash хийдэггүй. |
| ROS 1 | REP-3: Noetic нь Ubuntu 20.04, Python 3.8 орчинтой; support хугацаа 2025-05-д дууссан. | Одоо суусан ROS 1-ийг хадгалах шаардлагатай үед catkin adapter ашиглана. Python 2/Melodic орчныг шууд дэмжинэ гэж үзэхгүй. |
| ROS 2 | REP-2000: Humble-ийн Ubuntu 22.04 arm64 нь Tier 1; Jazzy-ийн Ubuntu 24.04 arm64 нь Tier 1. | ROS 2 хувилбарыг installer автоматаар сонгохгүй. Суулгасан distribution-ийн setup болон build workspace-ийг тодорхой заана. |
| Jetson.GPIO | NVIDIA-ийн library нь BOARD, BCM, CVM, TEGRA_SOC mode дэмждэг; BOARD нь 40-pin header-ийн physical дугаар. Permission/udev болон pinmux тохиргоо шаардлагатай. | Backend нь `Jetson.GPIO` + зөвхөн баталгаажсан BOARD mapping. Хуучин BCM 2/3-ыг шилжүүлдэггүй. Mock нь GPIO library импортлохгүй. |
| Bleak | 0.22.3 tag Python `>=3.8,<3.14`; Linux BlueZ `>=5.55`. Одоогийн 3.0.2 metadata Python `>=3.10`. | BLE нь нэмэлт hardware dependency; хуучин Python/BlueZ дээр хамгийн шинэ Bleak-ийг шууд суулгахгүй. `bluetoothctl --version`, Python, GATT property-г эхлээд шалгана. |
| Python ба ROS | Python ROS module нь тухайн ROS build-ийн interpreter-тэй нийцсэн байх ёстой. | ROS-ийн Python-оор `--system-site-packages` venv үүсгэж, ROS import-ыг шалгана. Windows Python-оор Jetson ROS-ийг баталсан гэж үзэхгүй. |

Эх сурвалжууд:

- NVIDIA: [JetPack 5.1.5](https://developer.nvidia.com/embedded/jetpack-sdk-515), [JetPack 6.2.1 release](https://forums.developer.nvidia.com/t/jetpack-6-2-1-jetson-linux-36-4-4-is-now-live/337333), [JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive).
- ROS-ийн өөрийн repository: [REP-3](https://github.com/ros-infrastructure/rep/blob/master/rep-0003.rst), [REP-2000](https://github.com/ros-infrastructure/rep/blob/master/rep-2000.rst). `docs.ros.org`/`ros.org` HTML хуудасны зарим нь access challenge буцаасан тул эдгээр албан ёсны эхийг ашиглав.
- NVIDIA: [Jetson.GPIO README, permissions, numbering, pinmux](https://github.com/NVIDIA/jetson-gpio), [Expansion headers / Jetson-IO](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/HR/ConfiguringTheJetsonExpansionHeaders.html). Сүүлийн холбоос нь r36.4.4-ийн жишээ; төхөөрөмжийн бодит L4T-тэй ижил хувилбарын guide-ийг дагана.
- Bleak: [0.22.3 Python constraints](https://github.com/hbldh/bleak/blob/v0.22.3/pyproject.toml), [0.22.3 supported platforms](https://github.com/hbldh/bleak/blob/v0.22.3/README.rst), [current Python constraints](https://github.com/hbldh/bleak/blob/develop/pyproject.toml), [Linux D-Bus backend](https://bleak.readthedocs.io/en/latest/backends/linux.html).

Pinmux нь Python GPIO pin сонгохоос тусдаа алхам. NVIDIA Jetson-IO нь supported development board дээр device tree тохиргоог өөрчилж, reboot-ийн дараа хэрэгжүүлдэг; production carrier дээр тухайн carrier-ийн pinmux spreadsheet/flash заавар шаардлагатай байж болно. Энэ төсөл автоматаар pinmux register бичихгүй, firmware flash хийхгүй.

Ubuntu, Python, BlueZ, ROS, carrier board-ийн нийлбэрийг хараахан баталгаажуулаагүй үед hardware install/deploy-ийг дууссан гэж үзэхгүй. Харин mock болон интерфейсийн шалгалтыг тусдаа хийж болно.
