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

## สำรอง / คืนค่าการตั้งค่า (พัฒนา v1.12)

เปิด **Application Settings → Backup / Restore Settings** แล้วเลือก **Export Settings** เพื่อสร้าง UTF-8 `MultiPortChecker-Backup-YYYYMMDD-HHMMSS.json` (รองรับ `.mpcbackup.json` ด้วย) รูปแบบ `MultiPortCheckerBackup` มี `backup_version: 1`, `app_version` ต้นทาง, `created_at`, `secrets_included: false`, `settings` และ `targets` รุ่นพัฒนาคือ `1.12.0-dev` ส่วนรุ่นเผยแพร่ยังเป็น v1.11.0

- รวม Host + Port, Device Name, Groups, ธีม, ตัวเลือก System Tray, ตัวเลือกเริ่มแบบซ่อน, State Change Alerts, ตัวเลือกเปิดผู้ให้บริการแจ้งเตือน, timeout, จำนวน retry และตัวเลือก Retry Later
- ไม่ส่งออกคีย์ข้อมูลลับ รวมถึง Generic Webhook URL, Teams endpoint, token, Authorization และ credentials โดย endpoint ในเครื่องปลายทางคงเดิม เปิดผู้ให้บริการภายนอกได้ต่อเมื่อ endpoint ในเครื่องผ่านการตรวจสอบ มิฉะนั้นจะปิดพร้อมคำเตือน
- ไม่รวม SQLite, Event History, Notification Delivery History, รายการส่งล้มเหลว, durable retry queue, หลักฐาน Availability และ maintenance audit history การนำเข้าไม่สร้างการเปลี่ยนสถานะหรือการแจ้งเตือนและไม่เขียนทับประวัติเหล่านี้
- การลงทะเบียน **Start with Windows** ใน registry เป็นข้อมูลเฉพาะเครื่อง ต้องเปิดเองบนเครื่องปลายทาง การนำเข้าตัวเลือกเริ่มแบบซ่อนไม่ลงทะเบียน startup

**Import Settings / Preview** แสดงข้อมูลต้นทาง จำนวนเป้าหมาย/กลุ่ม เป้าหมายใหม่/ตรงกัน ชื่อ/กลุ่มที่เปลี่ยน จำนวนรายการไม่ถูกต้อง/ซ้ำ และคำเตือน เลือกหมวด **Monitored Targets / Device Names / Groups**, **Application Preferences** และ/หรือ **Notification Behavior Settings** แล้วจึงยืนยัน:

- **Merge** เก็บเป้าหมายเดิม เพิ่ม Host + Port ใหม่ และแทน Device Name กับ Groups ของรายการที่ตรงกัน (รวมค่าว่างจากไฟล์) รายการเดิมคง TCP baseline และ maintenance ที่ใช้อยู่ เป้าหมายใหม่เริ่มแบบยังไม่ตรวจสอบและปิด maintenance
- **Replace** มีคำเตือนชัดเจนก่อนแทนรายการเป้าหมายทั้งหมด เป้าหมายหลังคืนค่าจะปิด maintenance ล้างเหตุผลและเวลา รายการที่ยังมี Host + Port เดิมคง TCP baseline และรายการที่ลบยังมีหลักฐานประวัติเดิม ทั้งสองโหมดไม่สร้าง maintenance audit event สมมติ

ก่อนนำไปใช้ต้องสร้างไฟล์ปลอดข้อมูลลับ `backups/Before-Import-YYYYMMDD-HHMMSS-ffffff.mpcbackup.json` ข้าง `mpc_config.json` ซึ่งอยู่ข้าง source หรือ EXE ไม่ใช่ `_MEIPASS` โฟลเดอร์ต้องเขียนได้ หากสำรองก่อนนำเข้าไม่สำเร็จจะหยุด การบันทึก config ใช้ไฟล์ชั่วคราวในโฟลเดอร์เดียวกันและแทนที่แบบ atomic ก่อนปรับ UI หากเขียนไม่สำเร็จจะคง config/UI เดิม หากปรับแอปล้มเหลวจะย้อนคืน และแจ้งชัดเจนหากเขียนย้อนคืนลงดิสก์ไม่ได้ ไม่มีการลบ safety backup อัตโนมัติ และไฟล์มีรายการเป้าหมายอยู่ด้วย

รอการตรวจสอบ/สแกนให้เสร็จก่อนนำเข้า จากนั้นค่าจะเปลี่ยนทันทีโดยไม่ต้องเริ่มแอปใหม่ จำกัดไฟล์ **5 MiB**, **10,000 เป้าหมาย**, Host ไม่ว่างยาวไม่เกิน **253 ตัวอักษร**, Port จำนวนเต็ม **1–65535**, ชื่อไม่เกิน **200 ตัวอักษร** และกฎ Groups เดิม **10 กลุ่ม / 32 ตัวอักษร** รายการไม่ถูกต้องจะข้ามและนับจำนวน Host + Port ซ้ำใช้รายการแรก ชนิดข้อมูลการตั้งค่าที่ผิดจะปฏิเสธไฟล์ ฟิลด์ที่ไม่รู้จักจะละเว้นพร้อมคำเตือนและไม่บันทึก ความเข้ากันได้อิงเวอร์ชันรูปแบบแยกจากรุ่นแอป: รูปแบบ 1 ยอมรับแอปต้นทางต่างรุ่น และปฏิเสธรูปแบบที่ยังไม่รองรับ

JSON เดิมของ **Save List / Load List** ยังแยกต่างหากและทำงานเหมือนเดิม CSV เป็นรายงาน/รายการ **ไม่ใช่ไฟล์สำรองการตั้งค่า** การสำรองข้อมูลในเครื่องทั้งหมดอยู่นอกขอบเขต v1.12

## ความสามารถ

- Start with Windows แบบต่อผู้ใช้ และเลือกเริ่มแบบซ่อนใน System Tray ได้
- หน้าต่าง Health / Diagnostics พร้อมส่งออก JSON ที่คุ้มครองข้อมูลลับ
- เพิ่มและลบเป้าหมาย Host/IP + TCP Port
- กำหนด Device Name แบบไม่บังคับและแก้ไขเป้าหมายเดิมได้โดยตรง
- ตรวจสอบ Ping หนึ่งครั้ง โดยแสดงค่าความหน่วง, `Timeout` หรือค่าสำรอง `Online`
- ตรวจสอบ TCP Port ด้วย socket พร้อมแสดงสถานะ ONLINE/OFFLINE ด้วยสี
- State Change Alerts สำหรับการเปลี่ยนสถานะ TCP เป็น DOWN และ RECOVERED พร้อมแสดง downtime
- บันทึกค่าเปิด/ปิด State Change Alerts โดยค่าเริ่มต้นเป็นเปิดใช้งาน
- Event History แบบถาวรที่แสดงรายการ DOWN และ RECOVERED ใหม่สุดก่อน
- กรองประวัติตาม Device/Host และ Event Type
- CSV Export ตามตัวกรองปัจจุบัน และ Clear History พร้อมการยืนยัน
- สถิติ Availability / Uptime สำหรับวันนี้, 7 วันแบบย้อนหลัง, 30 วันแบบย้อนหลัง และช่วงวันที่กำหนดเอง
- ค่า Availability และ Coverage พร้อม downtime, จำนวน outage, outage ที่นานที่สุด และ MTTR
- Outage Details พร้อมส่งออก Summary CSV และ Outage CSV แบบ UTF-8 with BOM
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
- Windows System Tray แบบ native พร้อมตัวควบคุมการเฝ้าติดตามเบื้องหลัง
- Minimize-to-Tray แบบเลือกได้และ Close-to-Tray ที่บันทึกการตั้งค่า
- ระบบ Notification แบบ provider สำหรับ Windows, Generic Webhook และ endpoint ที่รองรับ Microsoft Teams
- ส่ง Notification เบื้องหลังพร้อมกำหนด timeout และ retry ได้
- ประวัติการส่ง Notification แบบถาวรและคิว retry webhook แบบทนทานที่มีขอบเขต
- การจัดการ icon และ resource ที่รองรับ PyInstaller

## Device Name และข้อมูลเป้าหมาย

Device Name เป็นค่าที่ไม่บังคับ ใช้ตั้งชื่อที่จำได้ง่าย เช่น `Demo-PLC`, `NAS-01` หรือ `Printer-01` เลือกหนึ่งแถวและกด **Edit Selected** เพื่อเติมค่า Device Name, Host/IP และ Port ลงในช่องกรอก จากนั้นกด **Apply** เพื่ออัปเดตแถวโดยไม่ต้องลบและเพิ่มใหม่

ระเบียนที่บันทึกใหม่รองรับรูปแบบต่อไปนี้:

```json
{
  "name": "Demo-PLC",
  "host": "192.0.2.10",
  "port": 102,
  "groups": ["PLC", "Critical"],
  "maintenance": {
    "enabled": true,
    "started_at": "2026-09-08T10:00:00+07:00",
    "until": "2026-09-08T11:00:00+07:00",
    "reason": "Planned maintenance"
  }
}
```

ระเบียนเดิมที่ไม่มี `name` ยังคงโหลดได้โดยใช้ Device Name เป็นค่าว่าง และไม่ต้องย้ายข้อมูลด้วยตนเอง

## Device Groups / Tags และ Planned Maintenance Mode

กำหนด Groups / Tags แบบคั่นด้วย comma เช่น `PLC, Critical` ได้สูงสุด 10 กลุ่มต่อเป้าหมายและ 32 ตัวอักษรต่อกลุ่ม ระบบตัดช่องว่าง ค่าว่าง และค่าซ้ำแบบไม่สนตัวพิมพ์ กลุ่มเป็น metadata สำหรับจัดระเบียบเท่านั้น ไม่เปลี่ยน identity แบบ Host + Port, Ping/TCP หรือสร้าง monitoring session เพิ่ม ตัวกรอง **Group** มาจากเป้าหมายถาวรเท่านั้น การ monitor และ **Check All** ยังครอบคลุมเป้าหมายถาวรทั้งหมดแม้บางแถวถูกกรอง การกรองกลุ่มในรายงานใช้ config ปัจจุบัน ไม่ได้สร้างประวัติสมาชิกกลุ่มย้อนหลัง

เลือกเป้าหมายถาวรหนึ่งรายการแล้วกด **Start Maintenance** รองรับ Until manually ended, 30 นาที, 1, 2 หรือ 4 ชั่วโมง และ **Custom End Time** ตามเวลาท้องถิ่นที่ผ่าน validation เหตุผลเป็น plain text ไม่เกิน 200 ตัวอักษร ปุ่ม **End Maintenance** ใช้จบช่วงที่ active ส่วนช่วงกำหนดเวลาจะหมดอายุผ่าน Tk scheduler เพียงชุดเดียวซึ่งทำงานต่อเมื่อซ่อนหน้าต่าง manual/future maintenance ถูกคืนค่าหลังเปิดแอปใหม่ และสถานะที่หมดอายุแล้วจะถูกปิดเพียงครั้งเดียว

Maintenance แยกจาก TCP state และไม่ได้แปลว่าเป้าหมาย ONLINE ระบบยังตรวจ Ping/TCP, ใช้ `TcpStateTracker` เดิม และบันทึก DOWN/RECOVERED จริงใน Event History ระหว่าง maintenance ระบบระงับ Tk alert และ notification ใหม่ของ Windows/Generic Webhook/Teams ก่อน enqueue จึงไม่มี Notification Delivery History สำหรับ transition ที่ถูกระงับ แต่ไม่ยกเลิกหรือแก้ไข delivery/retry ที่สร้างก่อนเริ่ม maintenance

Event `MAINTENANCE_STARTED` และ `MAINTENANCE_ENDED` เก็บช่วงย้อนหลัง เหตุผล เวลาจบที่กำหนด และสาเหตุจบแบบ manual/expired หากจบ maintenance ขณะที่ TCP ยัง OFFLINE ระบบจะไม่ reset tracker หรือสร้าง DOWN ซ้ำ และ RECOVERED จริงครั้งถัดไปยังทำงานตามปกติ config เก่าที่ไม่มี `name`, `groups` หรือ `maintenance` โหลดได้ด้วยค่าเริ่มต้นว่าง/ปิด โดยไม่ต้อง migrate เอง

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

## Windows System Tray

ไอคอน notification area แบบ native ของ Windows จะเริ่มพร้อมแอปโดยไม่ใช้ runtime dependency ภายนอก การเปิดโปรแกรมเองตามปกติจะแสดงหน้าต่างหลัก ส่วน EXE ที่ลงทะเบียนผ่าน **Application Settings** สามารถใช้ `--start-hidden` เพื่อเริ่ม lifecycle เดิมครบถ้วนแต่ซ่อนหน้าต่างไว้ใน System Tray

เมนู tray มี **Open MultiPortChecker**, **Check All**, **Start Auto Refresh**, **Stop Auto Refresh**, **Event History**, **Availability Report**, **Notification Settings**, **Notification History** และ **Exit** คำสั่งเหล่านี้ใช้เส้นทางการเฝ้าติดตามและ Auto Refresh เดิม จึงมีรอบตรวจสอบและ Auto Refresh timer เพียงชุดเดียว คำสั่ง Report, History และ Settings จะคืนหน้าต่างหลักและเปิดหรือโฟกัสหน้าต่างที่มีอยู่

- **Hide to Tray** ซ่อนหน้าต่างหลักโดยตั้งใจ ขณะที่การเฝ้าติดตามยังทำงานต่อ
- **Minimize to tray** เลือกให้การ minimize ปกติเปลี่ยนเป็นการซ่อนได้ โดยค่าเริ่มต้นปิดอยู่
- **Close button minimizes to tray** เปิดโดยค่าเริ่มต้น เมื่อเปิดไว้ ปุ่ม X ของหน้าต่างหลักจะซ่อนแอปแทนการออก เมื่อปิดค่านี้ ปุ่ม X จะออกจากโปรแกรมทั้งหมด
- การตั้งค่า tray ทั้งสองค่าบันทึกใน `mpc_config.json` โดย config รุ่นเก่าจะใช้ค่าเริ่มต้นที่ปลอดภัยข้างต้น
- Auto Refresh, การติดตาม TCP State Change, การคำนวณ downtime และการบันทึก Event History ทำงานต่อขณะซ่อน โดยไม่สร้าง monitoring loop เพิ่ม
- กล่องแจ้งเตือน Tk แบบ native จะถูกพักไว้ขณะซ่อนและแสดงหลังคืนหน้าต่างหลัก เพื่อไม่ให้ modal dialog ที่มองไม่เห็นขัดขวางการเฝ้าติดตามเบื้องหลัง
- ใช้คำสั่ง **Exit** ในเมนู tray เพื่อปิด tray icon, monitoring executor, กระบวนการ Trace Route, หน้าต่าง Event History และแอป Tk อย่างสมบูรณ์

หากเริ่มไอคอน Windows tray ไม่สำเร็จ ปุ่ม Hide to Tray จะถูกปิดใช้งานและปุ่ม X ของหน้าต่างหลักจะออกจากโปรแกรมตามปกติ

## Windows Startup

เปิด **Application Settings** แล้วเลือก **Start MultiPortChecker with Windows** ฟังก์ชันนี้ใช้ได้กับ EXE ที่แพ็กด้วย PyInstaller เท่านั้น และลงทะเบียนเฉพาะผู้ใช้ปัจจุบันที่ `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` จึงไม่ใช้ HKLM และไม่ต้องใช้สิทธิ์ผู้ดูแลระบบ ตัวเลือก **Start hidden in System Tray** จะเพิ่ม `--start-hidden` เฉพาะคำสั่งที่ Windows เรียกตอนเข้าสู่ระบบ การเปิดโปรแกรมเองตามปกติยังคงแสดงหน้าต่างหลัก

เมื่อรันจาก source ระบบจะไม่อนุญาตให้ลงทะเบียน startup เพื่อป้องกันการบันทึก path ของ Python หรือโฟลเดอร์พัฒนาโดยไม่ตั้งใจ หากต้องการปิด ให้ยกเลิก checkbox แล้วบันทึก ระบบจะลบเฉพาะค่า `MultiPortChecker` และไม่แตะ startup entry อื่น

## Health / Diagnostics

เปิด **Health / Diagnostics** จากหน้าหลักหรือ **Application Settings** เพื่อดูสถานะรวม `HEALTHY`, `WARNING`, `ERROR` หรือ `UNKNOWN` snapshot แบบ on-demand แสดงโหมด source/frozen, uptime ของ process, จำนวน target/group, รอบ monitoring ล่าสุดและระยะเวลา, การตรวจ Auto Refresh ที่ค้าง, สถานะ worker แบบ bounded, สุขภาพฐานข้อมูล Event History, worker/queue ของ notification, จำนวน delivery แต่ละสถานะ, maintenance และเวลาหมดอายุที่ใกล้ที่สุด, Availability, System Tray, Windows Startup และผลตรวจ config

Target ที่ OFFLINE หรือเข้าถึงไม่ได้เป็นผล monitoring ปกติ ไม่ใช่ application error เมื่อเปิด Auto Refresh ระบบจะเตือน stale หลังไม่มี batch ที่ทำสำเร็จนานกว่า `max(3 × refresh interval, 60 seconds)` Diagnostics ใช้ state และ executor เดิม ไม่สร้าง monitoring engine เพิ่ม

ปุ่ม **Copy Summary** คัดลอกข้อความสรุป และ **Export Diagnostics** สร้างไฟล์ `MultiPortChecker-Diagnostics-YYYYMMDD-HHMMSS.json` ที่มีเฉพาะข้อมูลรวม โดยไม่ส่งออก webhook/Teams endpoint, token, Authorization header, password, credential, config ทั้งไฟล์, เนื้อหา Event History หรือรายชื่อ target/device

## Notification Framework

เลือก **Notification Settings** ในหน้าต่างหลักหรือ System Tray เพื่อกำหนด provider ที่ทำงานแยกจากกัน:

- **Windows Notifications** ใช้ไอคอน notification area แบบ native ที่มีอยู่และ Windows Shell APIs โดยไม่ต้องใช้แพ็กเกจ Notification ภายนอก
- **Generic Webhook** ส่ง HTTP `POST` พร้อม payload JSON แบบ UTF-8 สำหรับงาน automation
- **Microsoft Teams** ส่ง payload แบบ Adaptive Card ไปยัง webhook หรือ Workflow endpoint ที่รองรับ Teams ซึ่งผู้ใช้กำหนดเอง การใช้งานขึ้นอยู่กับ endpoint ที่ตั้งค่าไว้และไม่ได้สมมติว่า legacy connector แบบใดพร้อมใช้งานเสมอ

provider ทั้งหมดปิดโดยค่าเริ่มต้น การอัปเกรดจึงไม่ส่ง Notification ภายนอกโดยไม่คาดคิด Windows Notifications แยกจาก checkbox **State Change Alerts** เดิม ผู้ใช้สามารถเปิด dialog, Windows notification, ทั้งสองอย่าง หรือปิดทั้งหมดได้ Event History ยังคงทำงานเป็นอิสระจากการตั้งค่า Notification

Notification ใช้ TCP transition หลักชุดเดียวกับ alert และ Event History:

- `ONLINE -> OFFLINE` ส่ง Notification **DOWN** หนึ่งครั้ง
- `OFFLINE -> ONLINE` ส่ง Notification **RECOVERED** หนึ่งครั้งพร้อม downtime
- baseline เริ่มต้นแบบ `UNKNOWN`, สถานะซ้ำ, การเปลี่ยนเฉพาะ Ping, ผล Trace Route และเป้าหมายชั่วคราวจาก IP Range Scan จะไม่ส่ง Notification
- เป้าหมายจาก scan ที่ถูกยกระดับเป็นเป้าหมายถาวรจะส่ง Notification ได้หลังจากสร้าง baseline ปกติแล้วเท่านั้น

การส่งภายนอกใช้ background worker แบบ bounded เพียงหนึ่งชุด คำขอ HTTP จึงไม่บล็อก Tkinter, การเฝ้าติดตาม หรือ Event History แต่ละ transition จริงของอุปกรณ์จะถูกส่งแยกกัน ความล้มเหลวของ provider หนึ่งจะไม่หยุด provider อื่น HTTP จะถือว่าสำเร็จเมื่อได้สถานะ `2xx` โดยค่าเริ่มต้นใช้ timeout 5 วินาทีและ retry สองครั้งหลังจากรอ 1 และ 3 วินาที การตั้งค่ารองรับ timeout 1–30 วินาทีและ retry 0–5 ครั้ง ความล้มเหลวอัตโนมัติจะอัปเดตสถานะผลล่าสุดแบบย่อใน Notification Settings โดยไม่เปิด modal dialog ซ้ำ ๆ

แต่ละ provider มีปุ่ม **Test** Test Notification ใช้ชื่อสมมติ `Demo-Device` ทำงานเบื้องหลัง และไม่เปลี่ยน `TcpStateTracker` หรือ Event History ผลการทดสอบจะกลับมายัง Tk main thread และแสดงข้อความสำเร็จหรือล้มเหลวแบบย่อโดยไม่เปิดเผย URL ของ endpoint

Webhook URL อาจมี secret token ช่องข้อมูลจึงถูกปิดบังใน Notification Settings และมีตัวเลือก **Show webhook URLs** สำหรับแสดงอย่างชัดเจน URL จะไม่ถูกใส่ใน history, CSV export หรือข้อความวินิจฉัยการส่ง URL ถูกเก็บเป็น sensitive plain text ภายใน `mpc_config.json` ที่ถูก ignore ในเครื่อง จึงควรป้องกันการเข้าถึงไฟล์นี้ ระบบไม่ใช้การเข้ารหัสแบบกำหนดเองที่ทำให้เข้าใจผิด

เมื่อซ่อนแอป Event History, Notification Delivery History, การส่งทันที และ delayed retry ที่เปิดใช้งานจะทำงานต่อ ส่วน Tk alert dialog เดิมจะยังรอจนกว่าจะคืนหน้าต่างหลัก

## Notification Delivery History และ durable retry

เลือก **Notification History** ในหน้าต่างหลักหรือ System Tray หรือ **Delivery History** ใน Notification Settings เพื่อดูหนึ่งระเบียนถาวรต่อ provider ที่เปิดใช้งานสำหรับแต่ละเหตุการณ์ DOWN/RECOVERED จริง provider ที่ปิดใช้งานจะไม่สร้างระเบียน รายการใหม่สุดแสดงก่อนพร้อมสถานะ `QUEUED`, `RETRYING`, `DELIVERED` หรือ `FAILED`, จำนวนครั้งที่พยายาม, เวลาพยายามล่าสุด/ครั้งถัดไป และข้อผิดพลาดแบบย่อที่ตัดข้อมูลลับออก สามารถค้นหา Device/Host และกรอง Provider/Status ได้

นโยบายส่งครั้งแรกยังเหมือนเดิม: webhook จะส่งครั้งแรกและ immediate retry ตามค่าที่กำหนด (ค่าเริ่มต้นสองครั้ง) โดยรอ 1 และ 3 วินาที ทุกความพยายามจริงจะเพิ่ม attempt count ของระเบียนเดิม เปิด **Retry failed webhook deliveries later** เพื่อเพิ่ม durable retry หลัง immediate retry หมด ค่าเริ่มต้นเป็นปิดสำหรับทั้ง config ใหม่และ config v1.7 เดิม ตาราง retry ที่มีขอบเขตคือ 5, 15 และ 60 นาที สูงสุดสาม delayed cycles เฉพาะ HTTP 429, HTTP 5xx, timeout และความผิดพลาด network/TLS ชั่วคราวเท่านั้นที่ retry อัตโนมัติภายหลัง ส่วน HTTP 400/401/403/404 โดยทั่วไปจะเป็น `FAILED` ค่า `Retry-After` ของ 429 อาจขยายเวลารอได้แต่จำกัดสูงสุด 60 นาที

config key ที่เข้ากันได้กับรุ่นเดิมคือ `"notification_retry_later_enabled": false` หากไม่มีค่าหรือค่าไม่ถูกต้อง ระบบจะใช้ `false` อย่างปลอดภัย

งาน retry คงอยู่ข้ามการเปิดแอปใหม่ใน `events.db` ประมวลผลตาม timestamp ของเหตุการณ์เก่าสุดก่อนผ่าน worker แบบ bounded เดิม และใช้ config กับ endpoint ปัจจุบันของ provider ปุ่ม **Retry Selected** และ **Retry All Failed** ใช้ส่งระเบียนที่ล้มเหลวด้วยตนเองหลังแก้ config แม้ automatic retry จะครบแล้ว การ retry ใช้ snapshot และ timestamp เดิม ไม่สร้าง TCP transition หรือ Event History ใหม่ DOWN ที่ยังส่งไม่สำเร็จจะไม่ถูกยกเลิกเมื่อเกิด RECOVERED ดังนั้นทั้งสองเหตุการณ์ยังส่งแยกกันตามลำดับเวลาได้

Delivery History ไม่เก็บ webhook URL, path, query token, Authorization header, request header, response body หรือ credential โดยเก็บเพียง provider key และหมวด/ข้อความที่ปลอดภัย เช่น `HTTP 500` Test Notification เป็นเพียงการวินิจฉัยและจะไม่เข้า Event History, Delivery History หรือ durable queue การส่ง Windows จะบันทึก `DELIVERED` เมื่อ Windows Shell รับคำสั่ง ซึ่งไม่ได้ยืนยันว่าผู้ใช้เห็น balloon และจะไม่มี delayed retry สำหรับ Windows

ระบบเก็บ terminal delivery records ใหม่สุด 20,000 แถว และไม่ตัด `QUEUED` หรือ `RETRYING` ปุ่ม **Clear History** ที่ต้องยืนยันจะลบเฉพาะ `DELIVERED`/`FAILED` โดยไม่เปลี่ยนงานที่ active หรือ Event History

## Event History

Event History บันทึกและกรอง `MAINTENANCE_STARTED` / `MAINTENANCE_ENDED` ด้วย แถว audit เก็บเฉพาะ reason/end metadata ในเครื่อง ส่วน TCP ที่เกิดระหว่าง maintenance ยังคงเป็น DOWN/RECOVERED และมี suppression audit flag ใน CSV ระบบไม่คัดลอก groups ลงทุก event แต่ตัวกรอง Group ใช้สมาชิกจาก config ปัจจุบัน

เลือก **Event History** เพื่อเปิดหน้าต่างแยกที่รองรับ theme และแสดงการเปลี่ยนสถานะ TCP แบบถาวรโดยเรียงรายการใหม่สุดก่อน ผลค่าอ้างอิง (`UNKNOWN -> ONLINE` และ `UNKNOWN -> OFFLINE`) จะไม่ถูกบันทึก สถานะที่ซ้ำกัน, การเปลี่ยนเฉพาะ Ping, ผล Trace Route และเป้าหมายชั่วคราวจาก IP Range Scan จะไม่สร้างประวัติเช่นกัน

ตารางประวัติแสดง:

```text
Date / Time | Device | Host / IP | Port | Event | Ping | Downtime
```

- ค้นหาด้วย Device Name หรือ Host/IP
- กรอง Event Type ด้วย **All**, **DOWN**, **RECOVERED**, **MAINTENANCE_STARTED** หรือ **MAINTENANCE_ENDED**
- **Export CSV** ส่งออกแถวตามตัวกรองปัจจุบัน พร้อม timestamp, สถานะก่อน/หลัง, ค่า downtime วินาทีดิบ และค่า downtime ที่จัดรูปแบบแล้ว ไฟล์ใช้ UTF-8 พร้อม BOM เพื่อรองรับชื่อภาษาไทยและ Unicode อื่นใน Microsoft Excel
- **Clear History** ต้องยืนยันและลบเฉพาระเบียนประวัติ โดยไม่กระทบเป้าหมายที่เฝ้าติดตาม, สถานะการเฝ้าติดตามปัจจุบัน หรือการตั้งค่า

Event History ใช้ฐานข้อมูล SQLite จาก standard library ชื่อ `events.db` ในโฟลเดอร์แอปที่เขียนได้เดียวกับ config ไฟล์และตารางจะถูกสร้างโดยอัตโนมัติเมื่อใช้ประวัติครั้งแรก และจะไม่ถูกรวมใน EXE ระบบจะเก็บเหตุการณ์ใหม่สุด 10,000 รายการและตัดแถวเก่ากว่าออกหลังการเพิ่มข้อมูล

## Availability Report

รายงานแบบ read-only ใช้ TCP และ maintenance events ที่ยังถูกเก็บใน Event History โดย Host + Port ยังเป็น identity ตัวกรอง Group ใช้สมาชิกกลุ่มจาก config ปัจจุบันและไม่รวมแถว scan ชั่วคราว

- **Raw Availability** คือผล TCP แบบเดิมของ v1.9: known uptime / known duration และไม่เปลี่ยนเพราะ maintenance
- **Operational Eligible Duration** = known duration ลบ known duration ที่อยู่ใน planned maintenance
- **Operational Availability** = known uptime นอก maintenance / operational eligible duration และแสดง `-` เมื่อตัวหารเป็นศูนย์
- **Planned Maintenance** คือ union ของช่วง maintenance ที่บันทึกถาวรและตัดตามช่วงรายงาน รวมทั้งส่วน online, offline และ unknown
- **Planned Downtime** คือ intersection ของ known TCP downtime, maintenance และช่วงรายงาน
- **Unplanned Downtime** คือ raw downtime ลบ planned downtime โดย outage แบ่งเป็น `PLANNED`, `UNPLANNED` หรือ `MIXED` และ Outage Details แสดง maintenance overlap
- **Coverage** ยังคงเป็น known duration / requested duration ช่วง UNKNOWN ระหว่าง maintenance ยังเป็น unknown ไม่กลายเป็น uptime หรือ coverage เพิ่ม

ช่วง maintenance ที่คร่อมขอบรายงานจะถูกตัด ช่วงที่ยัง active จะนับถึง report end และช่วงซ้อนกันจะถูกรวม รายงานย้อนหลังใช้ audit events ที่ persist ไม่พึ่งเฉพาะ flag ใน config ปัจจุบัน Summary CSV เพิ่ม groups, raw/operational availability, planned maintenance และ planned/unplanned downtime ส่วน Outage CSV เพิ่ม overlap, unplanned duration และ classification และ Event CSV รองรับ maintenance event พร้อม audit metadata

เลือก **Availability Report** ในหน้าต่างหลักหรือ System Tray เพื่อคำนวณสถิติ uptime แบบอ่านอย่างเดียวจาก Event History ของ TCP `DOWN` และ `RECOVERED` ที่ยังถูกเก็บไว้ รายงานจัดกลุ่มเป้าหมายด้วย Host + Port จึงไม่รวมบริการคนละ port บน host เดียวกันเข้าด้วยกัน โดยใช้ Device Name ที่ตั้งค่าปัจจุบันก่อน หากไม่มีจึงใช้ชื่อล่าสุดที่ไม่ว่างในประวัติหรือ Host/IP เป้าหมายถาวรที่ตั้งค่าไว้แต่ยังไม่มีหลักฐานสถานะจะแสดง Availability `-`, Coverage `0.00%`, Downtime `-` และ outage เป็นศูนย์ ส่วนแถวชั่วคราวจาก IP Range Scan จะไม่รวมในรายงาน

ช่วงเวลามีความหมายตามเวลาท้องถิ่นดังนี้:

- **Today**: ตั้งแต่เที่ยงคืนท้องถิ่นถึงเวลาปัจจุบัน
- **7 Days**: 168 ชั่วโมงย้อนหลังจนถึงเวลาปัจจุบัน
- **30 Days**: 720 ชั่วโมงย้อนหลังจนถึงเวลาปัจจุบัน
- **Custom**: Start Date และ End Date แบบรวมวันที่ทั้งสองในรูปแบบ `YYYY-MM-DD`; วันที่ในอดีตครอบคลุมเต็มวันตามเวลาท้องถิ่น และช่วงที่จบวันนี้จะหยุดที่เวลาปัจจุบัน ระบบจะปฏิเสธวันที่ไม่ถูกต้อง, วันที่สิ้นสุดก่อนวันที่เริ่ม และช่วงที่ยังไม่เริ่ม

เหตุการณ์ล่าสุดก่อนเริ่มช่วงใช้กำหนดสถานะเริ่มต้น: `DOWN` หมายถึง OFFLINE และ `RECOVERED` หมายถึง ONLINE หากไม่มีหลักฐานก่อนหน้า เวลาก่อนเหตุการณ์แรกที่ยังเก็บไว้จะเป็น UNKNOWN และไม่ถูกสมมติว่าออนไลน์ สถานะที่ทราบจะต่อเนื่องไปจนถึงเหตุการณ์ถัดไปหรือจุดสิ้นสุดรายงาน `DOWN` ซ้ำขณะ offline และ `RECOVERED` ซ้ำขณะ online จะถูกละเว้น ส่วน `RECOVERED` ขณะ unknown จะเริ่มสถานะ online ที่ timestamp นั้น

การคำนวณ metric:

- **Availability %** = known uptime / known duration × 100 โดยไม่ใช้ช่วง UNKNOWN เป็นตัวหาร
- **Coverage %** = known duration / ระยะเวลารายงานที่ขอ × 100 เพื่อแสดงหลักฐานที่ไม่ครบถ้วนอย่างชัดเจน
- **Total Downtime**, **Outage Count**, **Longest Outage** และ **Average Outage Duration** ใช้เฉพาะส่วนที่ outage ซ้อนทับกับช่วงรายงาน
- **MTTR** คือค่าเฉลี่ยระยะเวลาเต็มของ outage ที่ RECOVERED ภายในช่วงรายงาน และแสดง `-` หากยังไม่มี outage ที่เสร็จสิ้นก่อนจุดสิ้นสุดรายงาน

Outage ที่คร่อมขอบช่วงจะถูกตัดให้ตรงช่วงสำหรับการคำนวณ downtime ใน **Outage Details** ยังแสดง timestamp DOWN/RECOVERED จริงที่เก็บไว้ และแยก Actual Duration ออกจาก Period Downtime เหตุการณ์ DOWN ที่ยังไม่มี RECOVERED จะมีสถานะ **ONGOING** และนับถึงจุดสิ้นสุดรายงาน/เวลาปัจจุบันเท่านั้น ช่องค้นหา Device/Host กรองทั้ง summary และรายละเอียด และสามารถเรียงตาม Device, Availability, Downtime และ Outages ได้

**Export Summary CSV** ส่งออกแถว summary ที่ผ่าน filter ปัจจุบัน ส่วน **Export Outages CSV** ส่งออกรายละเอียด outage ที่ผ่าน filter ทั้งสองแบบใช้ UTF-8 พร้อม BOM เพื่อรองรับ Excel และชื่อ Unicode และไม่มีข้อมูล notification หรือ webhook

Availability อ้างอิงสถานะ TCP เท่านั้น ผล Ping เพียงอย่างเดียว, Trace Route, สถานะการส่ง notification, ผล webhook และแถว scan ชั่วคราวไม่มีผล การสร้างรายงานทำงานบน background worker แบบ bounded และไม่แก้ไข Event History, Notification Delivery History, monitoring state, notification หรือ retry

Event History เป็นแหล่งประวัติแหล่งเดียว การล้าง Event History จะลบหลักฐานที่ต้องใช้สร้างรายงานย้อนหลังของช่วงนั้นอย่างถาวร และไม่มีข้อมูลสำรองที่ซ่อนอยู่ เนื่องจากระบบเก็บ Event History ใหม่สุดเพียง 10,000 แถว ความลึกของรายงานจึงจำกัดตาม retention นี้ และช่วงเก่าที่ข้อมูลหายไปจะแสดงเป็น unknown coverage แทนการนับเป็น uptime

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

`mpc_config.json` เก็บ preference `start_hidden_on_windows_startup` แบบเลือกได้ โดย config เก่าใช้ค่าเริ่มต้น `false` ส่วนสถานะเปิดใช้งาน startup จริงจะอ่านจาก Windows registry เสมอ ไม่อนุมานจาก preference นี้

## การสร้าง Windows EXE

ติดตั้ง PyInstaller ใน build environment แล้วใช้ spec file ที่ track ไว้:

```powershell
pyinstaller --clean --noconfirm MultiPortChecker.spec
```

ไฟล์ที่รันได้จะถูกสร้างที่ `dist\MultiPortChecker.exe` canonical spec ที่ track ไว้จะรวม `assets/icon_network_transparent.ico` สำหรับทั้ง executable และหน้าต่างแอป เครื่องปลายทางไม่จำเป็นต้องติดตั้ง Python

## โครงสร้างโปรเจกต์

```text
multi_port_checker.py       Tkinter UI and background task coordination
app_version.py              เวอร์ชันแอปส่วนกลาง
settings_backup.py          ตรวจสอบ วางแผนคืนค่า และบันทึก backup แบบ atomic
settings_backup_ui.py       หน้าต่าง backup/restore และ preview แบบเลือกหมวด
application_health.py       health snapshot/export ที่ไม่ขึ้นกับ UI และปกป้องข้อมูลลับ
windows_startup.py          ตัวช่วยลงทะเบียน startup ต่อผู้ใช้สำหรับ frozen EXE
network_checks.py           Ping, TCP, IPv4 validation, and scan-plan helpers
monitoring_state.py         Host-record compatibility and TCP state tracking
event_history.py            SQLite Event History and CSV export helpers
maintenance.py              Group normalization and planned-maintenance helpers
availability_report.py      การสร้างช่วง uptime และ CSV report ที่ไม่ขึ้นกับ UI
notification_history.py     SQLite delivery history and durable retry state
windows_tray.py             Native Windows notification-area integration
notification_models.py      Notification events and backward-compatible settings
notification_manager.py     Bounded background delivery and retry coordinator
windows_notifications.py   Native Windows notification provider
webhook_notifications.py   Generic and Teams-compatible webhook providers
assets/
  icon_network_transparent.ico
tests/
  test_ping_helpers.py        Ping/TCP helper tests
  test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
  test_trace_route_helpers.py Trace command and input-validation tests
  test_monitoring_state.py    Device-record, transition, and duration tests
  test_event_history.py       Event storage, filtering, retention, and CSV tests
  test_availability_report.py Availability intervals, metrics, filters, and CSV tests
  test_device_groups.py       Group normalization, filtering, persistence, and CSV tests
  test_maintenance_mode.py    Maintenance state, audit, suppression, and report tests
  test_tray_helpers.py        Tray preferences, actions, and lifecycle tests
  test_notification_manager.py Notification settings, transitions, queue, and shutdown tests
  test_notification_history.py Delivery storage, filtering, retention, and recovery tests
  test_notification_retry_queue.py Durable/manual retry and localhost integration tests
  test_webhook_notifications.py Local HTTP delivery and payload tests
  test_windows_notifications.py Native notification formatting/provider tests
  test_windows_startup.py     การทดสอบ registry, command, config และ start-hidden
  test_application_health.py การทดสอบ health, DB, privacy และ export
  test_settings_backup.py     ทดสอบรูปแบบ backup การนำเข้า และความปลอดภัยไฟล์
  test_settings_backup_integration.py ทดสอบคืนค่าและ rollback ด้วย Tk แยกข้อมูล
MultiPortChecker.spec       PyInstaller build configuration
README.md
README_TH.md
CHANGELOG.md
```

Screenshot สำหรับเอกสารในอนาคตต้องใช้ข้อมูลสมมติที่ผ่านการตรวจสอบความปลอดภัยและเก็บไว้ใต้ `docs/images/` ขณะนี้ยังไม่มี screenshot สำหรับเอกสารใน repository

## การทดสอบ

```powershell
python -m unittest discover -s tests -v
python -m compileall -q settings_backup.py settings_backup_ui.py app_version.py application_health.py windows_startup.py multi_port_checker.py network_checks.py monitoring_state.py maintenance.py event_history.py availability_report.py notification_history.py windows_tray.py notification_models.py notification_manager.py windows_notifications.py webhook_notifications.py tests
```

## แผนงานในอนาคต

- visualization สำหรับรายงานและ Maintenance Overview เพิ่มเติม
