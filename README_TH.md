<p align="right">
  <a href="README.md">
    <img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge">
  </a>
  <a href="README_TH.md">
    <img src="https://img.shields.io/badge/ภาษา-ไทย-green?style=for-the-badge">
  </a>
</p>

# Multi Host Port Checker

แอปพลิเคชันเดสก์ท็อป Tkinter สำหรับ Windows ที่ใช้เฝ้าติดตามอุปกรณ์ที่ตั้งชื่อไว้ ค่าความหน่วงของ ICMP Ping และสถานะการเชื่อมต่อ TCP Port ของเป้าหมายรายตัวหรือช่วง IPv4

ผลลัพธ์ของ Ping และ TCP แยกจากกัน: Host อาจตอบสนองต่อ Ping แต่ TCP Port ที่กำหนดอาจ offline หรือ Host อาจบล็อก Ping แต่บริการ TCP ยังคง online

[![Download EXE](https://img.shields.io/badge/Download-MultiPortChecker.exe-brightgreen?style=for-the-badge)](https://github.com/wittayamon/tk-port-checker/releases/latest/download/MultiPortChecker.exe)

## ความสามารถ

- เพิ่มและลบเป้าหมาย Host/IP + TCP Port
- กำหนด Device Name แบบไม่บังคับและแก้ไขเป้าหมายเดิมได้โดยตรง
- ตรวจสอบ Ping หนึ่งครั้ง โดยแสดงค่าความหน่วง, `Timeout` หรือค่าสำรอง `Online`
- ตรวจสอบ TCP Port ด้วย socket พร้อมแสดงสถานะ ONLINE/OFFLINE ด้วยสี
- State Change Alerts สำหรับการเปลี่ยนสถานะ TCP เป็น DOWN และ RECOVERED พร้อมแสดง downtime
- บันทึกค่าเปิด/ปิด State Change Alerts โดยค่าเริ่มต้นเป็นเปิดใช้งาน
- Event History แบบถาวรที่แสดงรายการ DOWN และ RECOVERED ใหม่สุดก่อน
- กรองประวัติตาม Device/Host และ Event Type
- CSV Export ตามตัวกรองปัจจุบัน และ Clear History พร้อมการยืนยัน
- Check Selected และ Check All
- Auto Refresh ที่ไม่ทำงานซ้อนกัน
- ตรวจสอบในพื้นหลังด้วย worker pool แบบจำกัดขนาด ทำให้ UI ตอบสนองได้ตลอด
- IPv4 Range Scan พร้อมความคืบหน้าและการยกเลิก
- เลือกแสดง IP ที่สแกนทั้งหมดได้
- แถว Host/IP + Port ที่ซ้ำกันจะถูกอัปเดตแทนการเพิ่มใหม่
- Windows Trace Route แบบ streaming พร้อมกำหนดจำนวน hop และเวลารอการตอบกลับได้
- บันทึกและโหลดรายการ Host ในรูปแบบ JSON
- โหลด Host ที่บันทึกไว้และการตั้งค่า theme โดยอัตโนมัติ
- Theme แบบ Dark และ Light
- การจัดการ icon และ resource ที่รองรับ PyInstaller

## Device Name และข้อมูลเป้าหมาย

Device Name เป็นค่าที่ไม่บังคับ ใช้ตั้งชื่อที่จำได้ง่าย เช่น `Demo-PLC`, `NAS-01` หรือ `Printer-01` เลือกหนึ่งแถวและกด **Edit Selected** เพื่อเติมค่า Device Name, Host/IP และ Port ลงในช่องกรอก จากนั้นกด **Apply** เพื่ออัปเดตแถวโดยไม่ต้องลบและเพิ่มใหม่

ระเบียนที่บันทึกใหม่รองรับรูปแบบต่อไปนี้:

```json
{
  "name": "Demo-PLC",
  "host": "192.168.1.100",
  "port": 102
}
```

ระเบียนเดิมที่ไม่มี `name` ยังคงโหลดได้โดยใช้ Device Name เป็นค่าว่าง และไม่ต้องย้ายข้อมูลด้วยตนเอง

## IPv4 Range Scan

กรอก Start IP, End IP และ TCP Port สำหรับช่วงที่รวมทั้งค่าเริ่มต้นและสิ้นสุด จากนั้นเลือก **Scan** ตัวอย่าง:

```text
Start IP: 192.168.1.1
End IP:   192.168.1.254
Port:     443
```

ป้ายความคืบหน้าจะแสดงค่าเช่น `Scanning 37 / 254` ปุ่ม **Cancel Scan** จะหยุดส่งที่อยู่ใหม่ทันทีและยกเลิกงานที่รออยู่ ส่วนการเรียกใช้งานเครือข่ายที่เริ่มทำงานแล้วจะได้รับอนุญาตให้ทำงานจนเสร็จอย่างปลอดภัย

โดยค่าเริ่มต้น การสแกนจะเพิ่มหรืออัปเดตเฉพาะเป้าหมายที่ตอบสนองต่อ Ping หรือมี TCP Port เปิดอยู่ เปิดใช้ **Show all scanned IPs** เพื่อแสดงผลลัพธ์ Ping-timeout/TCP-offline ด้วย แถวที่ค้นพบใหม่จากการสแกนเป็นผลลัพธ์ runtime และจะไม่ถูกเขียนลง config ของแอปโดยอัตโนมัติเมื่อปิดแอป ใช้ **Save List** หากต้องการส่งออกแถวที่แสดงอยู่โดยตั้งใจ

แถวที่ค้นพบใหม่จะเริ่มด้วย Device Name ว่างและไม่สร้าง State Change Alerts การเพิ่มหรือแก้ไขเป้าหมายที่ค้นพบด้วยตนเองจะยกระดับให้เป็นเป้าหมายถาวร จากนั้นการตรวจ TCP ตามปกติครั้งแรกจะสร้างค่าอ้างอิงเริ่มต้นสำหรับการแจ้งเตือน

ช่วงจะต้องประกอบด้วยที่อยู่ IPv4 ที่ถูกต้อง End IP ต้องไม่ต่ำกว่า Start IP และการสแกนจำกัดไว้ที่ 1,024 ที่อยู่ ให้หยุด Auto Refresh และรอให้การตรวจสอบที่กำลังทำงานเสร็จก่อนเริ่ม IP Range Scan

## Trace Route

เลือกแถว Host/IP เพียงหนึ่งแถวและเลือก **Trace Route** หน้าต่างแยกที่ปรับขนาดได้จะรันการ trace และแสดง output ดิบของ `tracert` ที่ทยอยส่งมา รองรับทั้งที่อยู่ IPv4 และ DNS hostname เช่น `example.com`

คำสั่งเริ่มต้นคือ:

```powershell
tracert -d -h 15 -w 1000 <host>
```

- `-d` ปิดการค้นหา DNS hostname ของ hop ระหว่างทาง ซึ่งช่วยหลีกเลี่ยงความล่าช้าจากการค้นหา
- **Max Hops** มีค่าเริ่มต้น 15 และรับค่าได้ตั้งแต่ 1 ถึง 255
- **Timeout** คือเวลารอต่อการตอบกลับหนึ่งครั้งในหน่วยมิลลิวินาที มีค่าเริ่มต้น 1000 ms และรับค่าได้ตั้งแต่ 1 ถึง 60000 ms
- **Run Again** ล้าง output และเริ่ม trace ใหม่ด้วยค่าขีดจำกัดปัจจุบัน
- **Stop** ยุติ trace ที่กำลังทำงาน, **Copy** คัดลอก output ปัจจุบันทั้งหมด และ **Close** หยุด trace ที่กำลังทำงานอย่างปลอดภัยก่อนปิดหน้าต่าง

Ping, สถานะ TCP และ Trace Route เป็นสัญญาณวินิจฉัยที่แยกจากกัน hop ที่ timeout (`* * *`) ไม่ได้พิสูจน์ว่าปลายทางหรือบริการ TCP offline เนื่องจาก router ระหว่างทางอาจไม่สนใจข้อความ ICMP TTL-expired ผล Trace จะไม่เปลี่ยนสถานะ ONLINE/OFFLINE ในตาราง

## คอลัมน์สถานะ

```text
Device Name | Host / IP | Port | Ping (ms) | Status
```

- ค่า Ping อาจเป็น `7 ms`, `<1 ms`, `Timeout` หรือ `Online` หาก Ping สำเร็จแต่ไม่สามารถแยกค่าความหน่วงได้
- ONLINE/OFFLINE แสดงสถานะของ TCP Port เสมอ ไม่ใช่สถานะ Ping

## State Change Alerts

เปิดหรือปิดการแจ้งเตือนด้วย **State Change Alerts** ค่านี้เปิดใช้งานโดยค่าเริ่มต้นและจะถูกบันทึกใน `mpc_config.json` config เดิมที่ไม่มีค่านี้จะเปิดใช้งานโดยค่าเริ่มต้นเช่นกัน

การแจ้งเตือนติดตามเฉพาะสถานะ TCP ระหว่าง **Check Selected**, **Check All** และ **Auto Refresh**:

- ผลครั้งแรก `UNKNOWN -> ONLINE` หรือ `UNKNOWN -> OFFLINE` จะสร้างค่าอ้างอิงเริ่มต้นและไม่แจ้งเตือน
- `ONLINE -> OFFLINE` สร้างคำเตือน **DEVICE DOWN** หนึ่งครั้ง
- ผล OFFLINE ที่ซ้ำกันจะไม่สร้างการแจ้งเตือนซ้ำ
- `OFFLINE -> ONLINE` สร้างข้อความ **DEVICE RECOVERED** หนึ่งครั้งพร้อม downtime ที่วัดได้
- หาก Device Name ว่าง ระบบจะใช้ Host/IP เป็นตัวระบุหลัก
- หากมีการเปลี่ยนสถานะมากกว่าสามรายการในรอบตรวจเดียวกัน ระบบจะรวมเป็นกล่องสรุปเดียว

Ping ยังคงเป็นข้อมูลสำหรับวินิจฉัย Ping `Timeout` จะไม่ทำให้เกิดการแจ้งเตือน DOWN ตราบใดที่ TCP Port ยัง ONLINE เป้าหมาย runtime ที่ค้นพบจาก IP Range Scan จะไม่เข้าร่วมการแจ้งเตือนจนกว่าจะถูกยกระดับให้เป็นเป้าหมายถาวร

## Event History

เลือก **Event History** เพื่อเปิดหน้าต่างแยกที่รองรับ theme และแสดงการเปลี่ยนสถานะ TCP แบบถาวรโดยเรียงรายการใหม่สุดก่อน ผลค่าอ้างอิง (`UNKNOWN -> ONLINE` และ `UNKNOWN -> OFFLINE`) จะไม่ถูกบันทึก สถานะที่ซ้ำกัน, การเปลี่ยนเฉพาะ Ping, ผล Trace Route และเป้าหมายชั่วคราวจาก IP Range Scan จะไม่สร้างประวัติเช่นกัน

ตารางประวัติแสดง:

```text
Date / Time | Device | Host / IP | Port | Event | Ping | Downtime
```

- ค้นหาด้วย Device Name หรือ Host/IP
- กรอง Event Type ด้วย **All**, **DOWN** หรือ **RECOVERED**
- **Export CSV** ส่งออกแถวตามตัวกรองปัจจุบัน พร้อม timestamp, สถานะก่อน/หลัง, ค่า downtime วินาทีดิบ และค่า downtime ที่จัดรูปแบบแล้ว ไฟล์ใช้ UTF-8 พร้อม BOM เพื่อรองรับชื่อภาษาไทยและ Unicode อื่นใน Microsoft Excel
- **Clear History** ต้องยืนยันและลบเฉพาระเบียนประวัติ โดยไม่กระทบเป้าหมายที่เฝ้าติดตาม, สถานะการเฝ้าติดตามปัจจุบัน หรือการตั้งค่า

Event History ใช้ฐานข้อมูล SQLite จาก standard library ชื่อ `events.db` ในโฟลเดอร์แอปที่เขียนได้เดียวกับ config ไฟล์และตารางจะถูกสร้างโดยอัตโนมัติเมื่อใช้ประวัติครั้งแรก และจะไม่ถูกรวมใน EXE ระบบจะเก็บเหตุการณ์ใหม่สุด 10,000 รายการและตัดแถวเก่ากว่าออกหลังการเพิ่มข้อมูล

## ข้อกำหนด

- Python 3.9 หรือใหม่กว่าเมื่อรันจาก source
- เป้าหมายหลักคือ Windows 10/11
- ไม่มี dependency ภายนอกสำหรับ runtime

## การรันจาก source

```powershell
python -m venv venv
venv\Scripts\activate
python multi_port_checker.py
```

## ข้อมูลที่บันทึก

รายการ Host รองรับ Device Name:

```json
{
  "name": "Demo-PLC",
  "host": "example.com",
  "port": 443
}
```

ระเบียนเดิมที่มีเฉพาะ `host` และ `port` ยังคงเข้ากันได้และจะโหลดโดยใช้ Device Name เป็นค่าว่าง ค่าความหน่วงของ Ping, สถานะ TCP, timestamp ของการขัดข้อง และผล Trace Route เป็นค่า runtime และจะไม่ถูกบันทึกในระเบียนรายการ Host

## การสร้าง Windows EXE

ติดตั้ง PyInstaller ใน build environment แล้วใช้ spec file ที่ track ไว้:

```powershell
pyinstaller --clean --noconfirm MultiPortChecker.spec
```

ไฟล์ที่รันได้จะถูกสร้างที่ `dist\MultiPortChecker.exe` canonical spec ที่ track ไว้จะรวม `assets/icon_network_transparent.ico` สำหรับทั้ง executable และหน้าต่างแอป เครื่องปลายทางไม่จำเป็นต้องติดตั้ง Python

## โครงสร้างโปรเจกต์

```text
multi_port_checker.py       Tkinter UI and background task coordination
network_checks.py           Ping, TCP, IPv4 validation, and scan-plan helpers
monitoring_state.py         Host-record compatibility and TCP state tracking
event_history.py            SQLite Event History and CSV export helpers
assets/
  icon_network_transparent.ico
tests/
  test_ping_helpers.py        Ping/TCP helper tests
  test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
  test_trace_route_helpers.py Trace command and input-validation tests
  test_monitoring_state.py    Device-record, transition, and duration tests
  test_event_history.py       Event storage, filtering, retention, and CSV tests
MultiPortChecker.spec       PyInstaller build configuration
README.md
README_TH.md
CHANGELOG.md
```

Screenshot สำหรับเอกสารในอนาคตต้องใช้ข้อมูลสมมติที่ผ่านการตรวจสอบความปลอดภัยและเก็บไว้ใต้ `docs/images/` ขณะนี้ยังไม่มี screenshot สำหรับเอกสารใน repository

## การทดสอบ

```powershell
python -m unittest discover -s tests -v
python -m compileall -q multi_port_checker.py network_checks.py monitoring_state.py event_history.py tests
```

## แผนงานในอนาคต

- รองรับ System tray
- การกรอง Event History ตามช่วงวันที่
