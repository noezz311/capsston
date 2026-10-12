# Jetson дээр бөглөх холболтын бүртгэл

Нэр, package version, GPIO model мэдээллийг Windows host-оос авахгүй. Доорх бүх талбар нь Jetson/Arduino төхөөрөмжийн бодит нотолгоонд тулгуурлана.

| Талбар | Бодит утга / нотолгоо |
|---|---|
| Jetson module model / carrier model / revision | Бөглөх |
| `/proc/device-tree/model` | Бөглөх |
| L4T / JetPack package / Ubuntu / architecture | Бөглөх |
| ROS_VERSION / ROS_DISTRO / setup.bash | Бөглөх |
| Python / BlueZ / Bleak / Jetson.GPIO | Бөглөх |
| Relay 1 physical BOARD pin / signal name / pinmux | Бөглөх |
| Relay 2 physical BOARD pin / signal name / pinmux | Бөглөх |
| Relay 1 / 2 active high эсвэл active low | Бөглөх |
| Startup / shutdown logical state | Бөглөх |
| Relay module voltage, logic voltage, ground/reference, isolated input | Бөглөх |
| Boot/reset үеийн relay төлөв / hardware pull resistor | Бөглөх |
| Door BLE address, characteristic UUID, write property | Бөглөх |
| LED BLE address, characteristic UUID, write property | Бөглөх |
| Linux service user/group, GPIO udev rule, BlueZ D-Bus access | Бөглөх |
| Хуучин controller system/user unit, cron, rc.local, tmux, container | Бөглөх |
| Баталгаажуулсан хүн, огноо, хэмжилтийн файл | Бөглөх |

Шалгах дараалал:

1. Мотор/механик ачааллыг тусгаарлаж, exact module + carrier pinout-ыг үйлдвэрлэгчийн баримтаас олно. Хуучин Raspberry Pi BCM 2/3-аас Jetson physical pin таамаглахгүй.
2. Ground/power/signal утас, relay active level-ийг схем ба хэмжилтээр тогтооно. GPIO logic voltage-д relay input тохирохыг шалгана; GPIO-д coil power шууд өгөхгүй.
3. Тохирох JetPack/L4T guide-ийн pinmux/Jetson-IO тохиргоог шалгаж, шаардлагатай reboot-ийн дараа дахин хэмжинэ. Программ `cleanup()` хийхэд pin input руу буцаж болох тул shutdown level-ийн дараах бодит төлөвийг hardware pull resistor-оор тогтоох шаардлагатай эсэхийг шалгана.
4. `gpio` permission-ийг owner service user-аар шалгана. Permission алдааг бүх веб серверийг root болгох аргаар шийдэхгүй.
5. BLE төхөөрөмжийг нэг нэгээр нь асааж address, GATT UUID, characteristic-ийн write mode-г шалгана. Кодын бодит routing нь DOOR=`50:8C:B1:69:D4:46`, DIR=`D8:A9:8B:AE:AE:86`; `main1.txt` comment үүнтэй зөрдөг ч командын зам таарч байгаа.
6. `OPEN\n`, `CLOSE\n` болон ганц байт `L`, `R`, `S`-ийг тестлэнэ. `S` нь LED бүх пиксел асаах команд; моторын emergency stop биш. LED зураг физик чиглэлтэй таарахыг нүдээр батална; firmware-ийн `drawArrow(true)`/`false` нэрнээс чиглэл таахгүй.
7. BLE disconnect/reconnect, холболтгүй timeout, web restart, owner SIGINT, цахилгаан тасрах/дахин асах үеийг тус тус шалгана. Timeout-ийн дараа өмнөх команд гүйцэтгэсэн эсэхийг тодруулахгүйгээр автоматаар давтахгүй.
8. Хаалганы нээгдсэн/хаагдсан бодит төлөвийг sensor/limit switch байхгүй үед баталгаатай гэж тайлагнахгүй. Arduino-ийн `Servo: OPEN (90)` лог ч servo target тавьсныг л нотлоно. BLE write амжилт ба физик байрлал тусдаа.
9. Хуучин controller-уудыг stop/mask хийж inventory-д тэмдэглэсний дараа шинэ hardware node-ийг нэг хувь ажиллуулна. Нэг owner lock нь хуучин, lock ашигладаггүй програмыг өөрөө зогсоож чадахгүй тул startup inventory заавал шаардлагатай.
