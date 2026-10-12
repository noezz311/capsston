# GitHub дахь төслийн хуулбар

Энэ repository нь Capstone төслийн код, Arduino firmware, deployment script,
тест болон техникийн баримтыг хадгална. GitHub-д код байршуулах нь Jetson дээрх
серверийг интернэтэд нээх эсвэл автоматаар ажиллуулах үйлдэл биш.

## Зөвхөн local орчинд хадгалах файлууд

`.gitignore` дараах файлуудыг GitHub-д оруулахаас хасна:

- `.venv/`, Python cache, build output болон log файлууд.
- Бодит `.env` файл, хувийн түлхүүр, SSH known-hosts болон төхөөрөмжийн generated тохиргоо.
- Нууц утга агуулсан хуучин `map-server.txt`, `monitor-server.txt` эх файлууд.
  Эдгээрийн local эх хувийг хэвээр хадгалсан. Орчны хувьсагчаас нууц утга уншдаг
  Jetson хувилбарууд `deployment/jetson/` дотор байна.
- `report/` дахь local тайлангийн draft файлууд.

`deployment/secrets.env.example` нь зөвхөн хоосон загвар бөгөөд repository-д орно.
Бодит нууц үг, session secret-ийг энэ загварт бичиж commit хийж болохгүй.

## Ubuntu terminal-аас татах

Private repository тул `noezz311` бүртгэл эсвэл энэ repository-д эрхтэй бүртгэлээр
GitHub-д нэвтэрсэн байх шаардлагатай. Git болон GitHub CLI (`gh`) суусан орчинд:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
git clone https://github.com/noezz311/capsston.git
cd capsston
git status
```

`gh` байхгүй бол [GitHub CLI-ийн Linux суулгах заавар](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)-ыг
ашиглана. Browser-гүй Ubuntu/SSH terminal дээр гарсан нэвтрэх хаяг, нэг удаагийн
кодыг өөрийн компьютерийн browser дээр ашиглаж нэвтэрч болно.

Дараа нь өөрчлөлт татах:

```bash
git pull --ff-only
```

Одоо байгаа Jetson deployment-ийн хавтсыг дарж бичихгүйгээр кодыг зэрэгцээ авах:

```bash
git clone https://github.com/noezz311/capsston.git ~/capsston-source
cd ~/capsston-source
```

Энэ нь файлуудыг татна; ажиллаж байгаа төхөөрөмжийн service, нууц тохиргоог өөрчлөхгүй.

Албан ёсны тайлбар: [GitHub clone](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository),
[GitHub CLI login](https://cli.github.com/manual/gh_auth_login).

## Ажиллуулах орчин

Төслийн ерөнхий тайлбарыг [README](../README.md), одоогийн Jetson deployment-ийн
мэдээллийг [Jetson README](../deployment/jetson/README.md)-ээс үзнэ.
Төхөөрөмжийн нууц тохиргоог хамгаалсан орчинд тусад нь үүсгэнэ.

Одоогийн `deployment/jetson/requirements.txt` нь Jetson Nano-ийн Python 3.6.9,
BlueZ 5.48 орчинд зориулсан хувилбаруудтай. Энгийн Ubuntu компьютер эсвэл өөр
Python хувилбар дээр ажиллахыг энэ upload-аар баталгаажуулаагүй. `start-web.sh`
болон `run-main1.sh` нь одоогийн `/home/lisa/capsston` deployment-д зориулсан
абсолют замтай тул шинэ clone дотроос шууд ажиллуулахгүй; эхлээд зорилтот
төхөөрөмж, runtime болон замыг тааруулна.
