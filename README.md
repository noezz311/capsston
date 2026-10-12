# Capstone — Jetson / ROS удирдлага, мониторинг

GitHub: [noezz311/capsston](https://github.com/noezz311/capsston) (private).
Ubuntu terminal-аас татах, шинэчлэлт авах заавар: [GitHub / Ubuntu](docs/github.md).

Raspberry Pi-ийн эх `map-server.txt`, `monitor-server.txt`, `main1.txt`, `old_main.txt`, `door_code.txt`, `led_code.txt` болон Arduino firmware-ийг хадгалсан. Ажиллуулах Python кодыг `capstone/` дотор тусад нь байрлуулав. Төхөөрөмжийн GPIO холболт баталгаажаагүй үед **mock** тохиргоог ашиглана. Windows компьютер нь Jetson биш; Windows дээрх mock үр дүн нь бодит GPIO/BLE/ROS middleware ажилласан гэсэн баталгаа болохгүй.

## Архитектур ба хадгалсан интерфейс

```text
Browser -- HTTP :8080 --> monitor-server (login / map_session cookie)
Browser -- HTTP :5000 --> control-server -- ROS command service --> hardware node
                                         <-- ROS status topic ---       |
                                                              GPIO + BLE owner
```

Нэг ROS hardware node GPIO/BLE төхөөрөмжийг эзэмшинэ. Веб процессуудад GPIO/BLE client байхгүй. Богино командын үр дүн шаардлагатай тул ROS service, тогтмол төлөв дамжуулахад status topic ашиглана; физик хаалга дууссан гэсэн баталгаагүй ажиллагааг action completion мэт тайлагнахгүй. Процессын owner lock болон legacy startup guard нь зэрэг асахаас сэргийлнэ.

| Сервер | Endpoint / команд | Ажиллагаа |
|---|---|---|
| Control, default 5000 | `GET /`, `GET /api/status`, `POST /api/cmd`, `GET /cmd/{cmd}`, `GET /logout` | Өмнөх замуудыг хадгална. Командад login шаардлагатай. |
| Monitor, default 8080 | `GET /`, `GET /login`, `POST /login` | Мониторинг ба HMAC session cookie; cookie нэр `map_session`. |
| Relay | `on`, `off` | Хоёр relay-г тохируулсан polarity-гаар удирдана. |
| Door | `open`, `close` | `50:8C:B1:69:D4:46` рүү `OPEN\n`, `CLOSE\n`. |
| LED | `left`, `right`, `stop` | `D8:A9:8B:AE:AE:86` рүү ганц байт `L`, `R`, `S`. `S` нь дэлгэцийн команд, emergency stop биш. |
| BLE | `reconnect` | Зөвхөн холболт сэргээх оролдлого; өмнөх командыг автоматаар дахин илгээхгүй. |

Default GATT characteristic UUID: `0000ffe1-0000-1000-8000-00805f9b34fb`. MAC mapping-ийг `map-server.txt` болон `main1.txt`-ийн **гүйцэтгэгддэг routing**-оос хадгалсан; `main1.txt`-ийн зөрүүтэй comment-оос сольсонгүй. `old_main.txt`-ийн RFCOMM serial хувилбарыг шинэ BLE service болгон давхар ажиллуулахгүй.

`relay`, `door_status`, `direction_status`, `door_ble`, `direction_ble`, `last_command`, `last_result`, `last_time`, `server_time`, `logged_in` гэсэн төлөвийн түлхүүрүүд хадгалагдана. Илгээсэн door command болон физик баталгаажсан төлөв тусдаа. Одоогийн firmware sensor feedback өгөхгүй тул амжилттай BLE write хийсэн ч `door_status` нь физик `OPEN` гэж батлахгүй. Timeout нь команд огт хэрэгжээгүйг батлахгүй; BLE write эхэлсэн байсан бол үр дүн тодорхойгүй байж болно.

## Jetson орчныг тогтоох

SSH destination дээр, төслийг хуулсан хавтсаас:

```bash
bash scripts/inspect_jetson.sh
```

Бодит model, carrier, Ubuntu, L4T/JetPack, Python, BlueZ, `/opt/ros` setup-уудыг хадгалж [нийцлийн баримт](docs/compatibility.md)-тай тулгана. ROS 1/2 distribution-ийг таамгаар суулгахгүй. Олон setup байвал ашиглах нэгийг тодорхой сонгоно. SSH hostname, user, project directory нь төхөөрөмж дээр баталгаажсан утга байна; service generator тэдгээрийг таамаглан бөглөхгүй.

## Dependency ба ROS build

Холбогдсон төхөөрөмжийн ROS-ийн Python interpreter-оор virtual environment үүсгэнэ. Доорх `$CAPSTONE_ROS_SETUP`, `$CAPSTONE_PROJECT`, `$CAPSTONE_WORKSPACE_SETUP`, `$CAPSTONE_PYTHON`, `$CAPSTONE_CONFIG` хувьсагчдыг бодит абсолют Linux замаар тохируулна. `CAPSTONE_ROS_VERSION` нь баталгаажсан `1` эсвэл `2` байна.

```bash
export CAPSTONE_PROJECT="$(pwd -P)"
# CAPSTONE_ROS_SETUP = inventory-оос сонгосон setup.bash-ийн абсолют зам
source "$CAPSTONE_ROS_SETUP"
python3 -m venv --system-site-packages "$CAPSTONE_PROJECT/.venv"
export CAPSTONE_PYTHON="$CAPSTONE_PROJECT/.venv/bin/python"
"$CAPSTONE_PYTHON" -m pip install -e "$CAPSTONE_PROJECT"
```

`python3-venv`, `python3-pip`, `build-essential`, тухайн ROS distribution-ийн build/dependency хэрэгслүүд хэрэгтэй. Jetson hardware mode-д BlueZ service/adapter, `Jetson.GPIO`, тохирох Bleak нэмэгдэнэ. Python/BlueZ-ийн хувилбарыг [нийцлийн хүснэгт](docs/compatibility.md)-тэй тулгалгүйгээр `pip install -U` хийхгүй. Python 3.8-д шинэ Bleak 3.x тохирохгүй; Bleak 0.22.3-ийн Linux суурь BlueZ 5.55-аас эхэлдэг. ROS import-ыг venv interpreter-оор шалгана:

```bash
# Зөвхөн сонгосон ROS хувилбарын мөрийг ажиллуулна:
"$CAPSTONE_PYTHON" -c 'import rclpy'  # ROS 2
"$CAPSTONE_PYTHON" -c 'import rospy'  # ROS 1
```

ROS package build-ийн exact команд болон local validation-ийн үр дүнг доорх build хэсэгт багц файлуудтай тулган оруулна.

## Тохиргоо ба authentication

Жишээ JSON тохиргоог өөр нэрээр хуулж, hardware mode-ийг `mock` хэвээр эхлүүлнэ. Config нь порт, GPIO pins/polarity, BLE address/UUID, timeout/reconnect болон ROS interface-ийг агуулна. Нууц үг, session secret-ийг source JSON-д оруулахгүй; `deployment/secrets.env.example`-ийг хувийн файлд хуулж бөглөнө.

```bash
# Утгуудыг өөрийн хамгаалсан env файлаас уншуулна. Шинэ нууц сонгоно.
set -a
source "$CAPSTONE_SECRET_ENV"
set +a
```

`CAPSTONE_ADMIN_USER`, `CAPSTONE_ADMIN_PASSWORD`, `CAPSTONE_SESSION_SECRET` нь control болон monitor дээр адил байна. Төслийн хуучин `.txt` дахь credential-ийг шинэ service автоматаар ашиглахгүй. Нууц файлыг `chmod 600` эсвэл `root:service-group` эзэмшилтэй `640` permission-оор хамгаална. Session secret солигдоход хуучин token хүчингүй болно. Config болон frontend-ийн порт ижил утгаас үүсдэг.

## Hardware баталгаажуулах

[Холболтын бүртгэл](docs/hardware-acceptance.md)-ийг бөглөнө. GPIO config нь `numbering: "BOARD"`, баталгаажсан physical pin-үүд, `active_high`, `startup_on`, `shutdown_on` утгатай байна. Hardware real mode нь `board_model_confirmed`, `pinmux_confirmed`, `wiring_confirmed`, `legacy_controllers_disabled` бүгд баталгаажсан, `/proc/device-tree/model` нь тохируулсан model-той таарсан үед л асна. Хуучин BCM 2/3 утга default mapping биш.

GPIO permission-ийг NVIDIA-ийн [Jetson.GPIO заавраар](https://github.com/NVIDIA/jetson-gpio) тохируулна: `gpio` бүлэг, сонгосон owner user-ийн membership, суусан library-ийн `99-gpio.rules`, udev reload/reboot. Төхөөрөмжийн өөрийн library замыг олж ашиглана; Python хувилбартай directory-г таамаглаж хуулж болохгүй. BlueZ нь system D-Bus-аар холбогдох тул service user-аар BLE scan/connect эрхийг тусад нь шалгана.

`hardware.owner_lock_path`-ийг real service-д `/run/capstone/hardware.lock` болгож болно; generated owner service нь энэ runtime directory-г үүсгэж, restart/stop үед lock файл байрлах directory-г хадгалдаг. Relay shutdown логик төлөв cleanup-ээс өмнө тавигдана; pin input руу суллагдсаны дараах цахилгаан төлөвийг external pull/electrical circuit хангана.

## Гараар ажиллуулах

Эхлээд legacy inventory-г дуусгаж owner-той давхар controller байхгүйг тогтооно. ROS болон workspace setup-ийг бүх terminal-д source хийнэ. Тус бүрийн terminal-д ижил JSON болон нууц env ашиглан:

```bash
bash "$CAPSTONE_PROJECT/deployment/run-service.sh" hardware-node
bash "$CAPSTONE_PROJECT/deployment/run-service.sh" control-server
bash "$CAPSTONE_PROJECT/deployment/run-service.sh" monitor-server
```

Эдгээр нь foreground процессууд тул гурван тусдаа terminal ашиглана. `Ctrl+C` нь owner cleanup/shutdown-ийг дуудна. ROS 1 ашиглаж байгаа бол баталгаажсан `ROS_MASTER_URI`-ийн master урьдчилан ажиллаж байх ёстой; энэ багц дурын master сонгож асаахгүй. Browser-оор `http://<Jetson-host>:8080/login` нээж, нэвтэрсний дараа `:5000` удирдлага руу шилжинэ. Owner байхгүй/тасарсан үед вебээс команд амжилттай мэт тайлагнахгүй.

## Systemd service бэлтгэх, асаах, лог харах

1. `systemctl list-unit-files`, `systemctl --user list-unit-files`, cron, `/etc/rc.local`, shell session/tmux, container, supervisor startup-ыг шалгана. `deployment/legacy-inventory.example.json`-ийг хуулж **бодит** хуучин system unit-ийн нэр, process pattern оруулна. Old user service/container/cron-ыг тусад нь зогсоож disable хийнэ. Шалгасан бол `reviewed` ба `external_startup_checked`-ийг `true` болгоно; хоосон service жагсаалт нь “байхгүйг шалгасан” утгатай.
2. Inventory дахь хуучин system controller unit бүрийг backup хийж, `sudo systemctl disable --now ACTUAL-OLD.service`, `sudo systemctl mask ACTUAL-OLD.service` хийнэ. Local unit file mask-д саад болж байвал файлыг backup-д шилжүүлж дараа нь mask хийнэ; stop/disable ганцаараа хангалтгүй. Startup guard masked бөгөөд inactive байхыг шалгадаг. Одоогийн төслийг боловсруулахдаа ямар ч remote service-ийг зогсоогоогүй.
3. Төхөөрөмжийн бодит хэрэглэгч, бүлэг, зам, env/config/inventory-г сонгож renderer ажиллуулна. Эдгээр хувьсагчид placeholder биш бодит утга өгнө:

```bash
"$CAPSTONE_PYTHON" scripts/render_systemd.py \
  --project "$CAPSTONE_PROJECT" \
  --python "$CAPSTONE_PYTHON" \
  --user "$CAPSTONE_SERVICE_USER" --group "$CAPSTONE_SERVICE_GROUP" \
  --config "$CAPSTONE_CONFIG" \
  --ros-setup "$CAPSTONE_ROS_SETUP" \
  --workspace-setup "$CAPSTONE_WORKSPACE_SETUP" \
  --ros-version "$CAPSTONE_ROS_VERSION" \
  --runtime-env "$CAPSTONE_RUNTIME_ENV" --secret-env "$CAPSTONE_SECRET_ENV" \
  --inventory "$CAPSTONE_LEGACY_INVENTORY" \
  --inventory-path "$CAPSTONE_LEGACY_INVENTORY" \
  --supplementary-group gpio \
  --output "$CAPSTONE_PROJECT/deployment/generated"
```

Mock ажиллуулахад `gpio` group хараахан үүсээгүй бол `--supplementary-group gpio` мөрийг орхино. `CAPSTONE_RUNTIME_ENV` нь generated runtime файл суух **зорьсон абсолют зам**. Renderer зөвхөн файл үүсгэнэ; service суулгах, асаахгүй. Generated env/units-ийн бүх замыг review хийнэ. Service user нь төсөл/config/setup/secret файлыг уншиж, Python ажиллуулах эрхтэй байх ёстой.

```bash
sudo install -m 0640 -o root -g "$CAPSTONE_SERVICE_GROUP" \
  deployment/generated/capstone-runtime.env "$CAPSTONE_RUNTIME_ENV"
sudo install -m 0644 deployment/generated/capstone-*.service /etc/systemd/system/
sudo install -m 0644 deployment/generated/capstone.target /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/capstone-*.service /etc/systemd/system/capstone.target
sudo systemctl daemon-reload
sudo systemctl enable --now capstone.target
systemctl status capstone-hardware capstone-control capstone-monitor --no-pager
journalctl -u capstone-hardware -u capstone-control -u capstone-monitor -f
```

Services нь `Restart=on-failure`, 3 секунд retry, 45 секунд shutdown timeout, SIGINT cleanup, journal log, `NoNewPrivileges` болон тодорхой `WorkingDirectory` ашиглана. Hardware unit нь inventory-д жагсаасан хуучин unit-тэй `Conflicts=` үүсгэж, startup бүрт guard ажиллуулна. Веб нь owner restart-ийн үеэр ажиллаж status/command failure-ийг харуулж чадна.

```bash
sudo systemctl stop capstone.target
sudo systemctl start capstone.target
sudo systemctl restart capstone-hardware.service
sudo systemctl disable --now capstone.target
```

## Буцаах

1. `sudo systemctl disable --now capstone.target` хийнэ; гурван capstone process зогссон, relay/механизмын аюулгүй төлөвийг хэмжиж шалгана. Гараар эхлүүлсэн capstone процесс байвал мөн Ctrl+C хийнэ.
2. Шинэ service/env/config-ийг backup хийнэ. Хуучин system unit-үүдийг өмнөх backup-аас restore хийж `sudo systemctl unmask ACTUAL-OLD.service`, `sudo systemctl daemon-reload` хийнэ. Өмнөх enable/disable төлөвийг inventory-гийн тэмдэглэлээс сэргээнэ.
3. Хуучин controller-ийг зөвхөн түүнд таарах hardware/OS дээр асаана. Raspberry Pi-ийн `RPi.GPIO`/BCM кодыг Jetson дээр шууд сэргээж ажиллуулахгүй; хуучин Raspberry Pi төхөөрөмж рүү буцах эсвэл баталгаажсан Jetson-compatible rollback хувилбар хэрэглэнэ.
4. Хуучин controller ажиллаж эхэлсний дараа шинэ owner-ийг давхар асаахгүй. Эх `.txt` болон Arduino firmware өөрчлөгдөөгүй тул original behavior-ийг харьцуулах эх хэвээр байна.

## Шалгалт ба үлдсэн баталгаа

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s deployment -p 'test_*.py' -v
python -m compileall -q capstone deployment scripts
```

Deployment guard/renderer-ийн 6 unit test Windows Python 3.13 дээр амжилттай: review хийгдээгүй inventory хориглох, unit/path injection хориглох, old unit stop+mask хоёрыг шаардах, legacy process илрүүлэх, unit-ийн explicit path/dependency/lock тохиргоо. `systemd-analyze`, actual systemd start, Jetson pinmux/relay, BLE radio/GATT болон ROS native build-ийг зөвхөн тохирох Linux/ROS төхөөрөмж дээр ажиллуулж батална. Энд эдгээрийг mock test-тэй адилтган амжилттай гэж үзэхгүй.

Real mode-д шилжихээс өмнө [hardware бүртгэл](docs/hardware-acceptance.md)-ийн model/carrier, pin mapping, relay polarity/startup/shutdown, BLE routing/write properties, service user/paths болон legacy inventory-г бүрэн бөглөх шаардлагатай.
