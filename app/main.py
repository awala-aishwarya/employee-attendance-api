

import os

import re

from datetime import datetime, timedelta, timezone, date

from datetime import UTC

from decimal import Decimal, ROUND_HALF_UP

from typing import Optional, Literal



from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from pymongo import ASCENDING, DESCENDING, MongoClient

from pymongo.errors import DuplicateKeyError

from pymongo.write_concern import WriteConcern



load_dotenv()



mongo_uri = os.getenv("MONGO_URI")

if not mongo_uri:

    raise RuntimeError("MONGO_URI must be configured in the environment or .env file")

from datetime import UTC

from pymongo import MongoClient



# Keep your existing environment variable names and loading code.

mongo_uri = os.getenv("MONGO_URI")

mongo_db_name = os.getenv("MONGO_DB")



client = MongoClient(

    mongo_uri,

    serverSelectionTimeoutMS=10000,

    tz_aware=True,

    tzinfo=UTC,

)



db = client[mongo_db_name]



IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

PRESENT_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}

ALL_STATUSES = PRESENT_STATUSES | {"ABSENT", "LEAVE"}



app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")





# ---------------------------- Shared utilities ---------------------------- #



def create_indexes():

    db.employees.create_index(

        [("emp_code", ASCENDING)], unique=True, name="uq_employees_emp_code"

    )

    db.employees.create_index(

        [("department", ASCENDING), ("emp_code", ASCENDING)],

        name="ix_employees_department_emp_code",

    )

    db.employees.create_index(

        [("department", ASCENDING), ("joined_on", ASCENDING)],

        name="ix_employees_department_joined",

    )

    db.attendance_logs.create_index(

        [("emp_code", ASCENDING), ("date", ASCENDING)],

        unique=True, name="uq_attendance_emp_code_date",

    )

    db.attendance_logs.create_index(

        [("date", DESCENDING), ("emp_code", ASCENDING)],

        name="ix_attendance_date_emp_code",

    )

    db.attendance_logs.create_index(

        [("emp_code", ASCENDING), ("date", DESCENDING)],

        name="ix_attendance_emp_date",

    )

    db.attendance_logs.create_index(

        [("status", ASCENDING), ("date", DESCENDING), ("emp_code", ASCENDING)],

        name="ix_attendance_status_date_emp",

    )





@app.on_event("startup")

def initialize_database():

    create_indexes()





def utc_now():

    return datetime.now(UTC).replace(microsecond=0)





def as_utc(value: datetime):

    if value.tzinfo is None:

        value = value.replace(tzinfo=UTC)

    return value.astimezone(UTC)





def as_ist(value: datetime):

    return as_utc(value).astimezone(IST)





def truncate_seconds(value: datetime):

    return value.replace(microsecond=0)





def epoch_ms(value):

    if value is None:

        return None

    return int(as_utc(value).timestamp() * 1000)





def parse_epoch_ms(value):

    if value is None:

        return truncate_seconds(utc_now())

    if isinstance(value, bool) or not isinstance(value, int):

        raise HTTPException(422, "Timestamp must be integer epoch milliseconds")

    if value < 100000000000 or value > 253402300799999:

        raise HTTPException(422, "Timestamp is out of range")

    try:

        return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)

    except (ValueError, OverflowError, OSError):

        raise HTTPException(422, "Timestamp is out of range")





def rounded(value, places=2):

    quantum = Decimal("1").scaleb(-places)

    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))





def valid_date(value):

    try:

        parsed = date.fromisoformat(value)

    except (ValueError, TypeError):

        raise HTTPException(422, "Date must use YYYY-MM-DD format")

    if parsed.isoformat() != value:

        raise HTTPException(422, "Date must use YYYY-MM-DD format")

    return parsed





def valid_month(value):

    if not re.fullmatch(r"\d{4}-\d{2}", value or ""):

        raise HTTPException(422, "Month must use YYYY-MM format")

    try:

        return datetime.strptime(value, "%Y-%m").date()

    except ValueError:

        raise HTTPException(422, "Invalid month")





def month_bounds(month):

    start = valid_month(month)

    if start.month == 12:

        following = date(start.year + 1, 1, 1)

    else:

        following = date(start.year, start.month + 1, 1)

    return start.isoformat(), (following - timedelta(days=1)).isoformat()





def attendance_date(punch_in, shift_start, shift_end):

    local = as_ist(truncate_seconds(punch_in))

    sh, sm = map(int, shift_start.split(":"))

    eh, em = map(int, shift_end.split(":"))

    if (eh, em) <= (sh, sm) and (local.hour, local.minute) < (eh, em):

        local -= timedelta(days=1)

    return local.date().isoformat()







def compute_late_minutes(punch_in, shift_start):

    local = as_ist(truncate_seconds(punch_in))



    h, m = map(int, shift_start.split(":"))

    start = local.replace(

        hour=h,

        minute=m,

        second=0,

        microsecond=0,

    )



    elapsed_seconds = (local - start).total_seconds()



    # Lateness is measured from shift start, with a 10-minute grace period.

    # Return zero if the punch-in is within the grace period.

    if elapsed_seconds <= 600:

        return 0



    return int(elapsed_seconds // 60)







def shift_end_instant(date_str, shift_start, shift_end):

    d = valid_date(date_str)

    sh = tuple(map(int, shift_start.split(":")))

    eh = tuple(map(int, shift_end.split(":")))

    if eh <= sh:

        d += timedelta(days=1)

    return datetime(d.year, d.month, d.day, eh[0], eh[1], tzinfo=IST).astimezone(UTC)





def compute_overtime(punch_out, shift_end, date_str, shift_start="09:30"):

    end = shift_end_instant(date_str, shift_start, shift_end)

    seconds = (as_utc(truncate_seconds(punch_out)) - end).total_seconds()

    return int(seconds // 60) if seconds >= 1800 else 0





def compute_work_hours(punch_in, punch_out):

    seconds = Decimal(str(

        (as_utc(truncate_seconds(punch_out)) -

         as_utc(truncate_seconds(punch_in))).total_seconds()

    ))

    if seconds < 0:

        raise HTTPException(422, "Punch-out must be after punch-in")

    return float((seconds / Decimal(3600)).quantize(

        Decimal("0.01"), rounding=ROUND_HALF_UP

    ))





def derive_fields(doc, emp):

    status = doc["status"]

    if status in {"ABSENT", "LEAVE"}:

        return {

            "punch_in": None, "punch_out": None, "work_hours": None,

            "late_minutes": 0, "overtime_minutes": 0, "half_day": False,

        }

    pin, pout = doc.get("punch_in"), doc.get("punch_out")

    if pin is None:

        raise HTTPException(422, "Presence status requires punch_in")

    pin = truncate_seconds(pin)

    if attendance_date(pin, emp["shift_start"], emp["shift_end"]) != doc["date"]:

        raise HTTPException(422, "punch_in does not belong to attendance date")

    result = {

        "punch_in": pin, "punch_out": None, "work_hours": None,

        "late_minutes": compute_late_minutes(pin, emp["shift_start"]),

        "overtime_minutes": 0, "half_day": False,

    }

    if pout is not None:

        pout = truncate_seconds(pout)

        if pout <= pin or (pout - pin).total_seconds() > 86400:

            raise HTTPException(422, "Invalid punch-out time")

        hours = compute_work_hours(pin, pout)

        result.update(

            punch_out=pout,

            work_hours=hours,

            overtime_minutes=compute_overtime(

                pout, emp["shift_end"], doc["date"], emp["shift_start"]

            ),

            half_day=hours < 4.50,

        )

    return result





def public_employee(doc):

    result = {k: v for k, v in doc.items() if k != "_id"}

    if "created_at" in result:

        result["created_at"] = epoch_ms(result["created_at"])

    return result





def public_attendance(doc):

    result = {k: v for k, v in doc.items() if k != "_id"}

    result.setdefault("history", [])

    result.setdefault("half_day", False)

    result.setdefault("late_minutes", 0)

    result.setdefault("overtime_minutes", 0)

    for key in ("punch_in", "punch_out"):

        result[key] = epoch_ms(result.get(key))

    for entry in result["history"]:

        entry["at"] = epoch_ms(entry["at"])

        for change in entry.get("changes", {}).values():

            for side in ("from", "to"):

                if isinstance(change.get(side), datetime):

                    change[side] = epoch_ms(change[side])

    return result





def make_json_safe(value):

    from bson import Timestamp, ObjectId, Binary

    from datetime import datetime, date

    from collections.abc import Mapping



    if isinstance(value, Mapping):

        return {

            str(key): make_json_safe(item)

            for key, item in value.items()

        }



    if isinstance(value, (list, tuple)):

        return [make_json_safe(item) for item in value]



    if isinstance(value, Timestamp):

        return {

            "time": value.time,

            "increment": value.inc,

        }



    if isinstance(value, ObjectId):

        return str(value)



    if isinstance(value, (Binary, bytes, bytearray, memoryview)):

        return {

            "binary_base64": __import__("base64").b64encode(

                bytes(value)

            ).decode("ascii")

        }



    if isinstance(value, (datetime, date)):

        return value.isoformat()



    return value







def pagination(page, page_size):

    if page < 1 or page_size < 1 or page_size > 100:

        raise HTTPException(422, "page must be >= 1 and page_size must be 1..100")

    return (page - 1) * page_size





def record_or_404(emp_code, date_str):

    doc = db.attendance_logs.find_one({"emp_code": emp_code, "date": date_str})

    if not doc:

        raise HTTPException(404, "Attendance record not found")

    return doc





# --------------------------------- Models --------------------------------- #



class EmployeeIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")

    name: str = Field(min_length=1, max_length=100)

    email: EmailStr

    department: str = Field(min_length=1, max_length=50)

    shift_start: str = "09:30"

    shift_end: str = "18:30"

    joined_on: str



    @field_validator("name", "department")

    @classmethod

    def nonblank(cls, value):

        if not value.strip():

            raise ValueError("Value must not be blank")

        return value



    @field_validator("shift_start", "shift_end")

    @classmethod

    def time_format(cls, value):

        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):

            raise ValueError("Time must use HH:MM")

        return value



    @field_validator("joined_on")

    @classmethod

    def date_format(cls, value):

        try:

            if date.fromisoformat(value).isoformat() != value:

                raise ValueError()

        except ValueError:

            raise ValueError("joined_on must use YYYY-MM-DD")

        return value



    @model_validator(mode="after")

    def different_shift_times(self):

        if self.shift_start == self.shift_end:

            raise ValueError("Shift start and end must differ")

        return self





class PunchInIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str

    punched_at: Optional[int] = None

    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"





class PunchOutIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    emp_code: str

    punched_at: Optional[int] = None





class CorrectionIn(BaseModel):

    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=5, max_length=200)

    regularized_by: str = Field(min_length=1, max_length=50)

    status: Optional[Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]] = None

    punch_in: Optional[int] = None

    punch_out: Optional[int] = None



    @field_validator("reason", "regularized_by")

    @classmethod

    def nonblank(cls, value):

        if not value.strip():

            raise ValueError("Value must not be blank")

        return value





# -------------------------------- Endpoints -------------------------------- #



@app.get("/health")

def health():

    try:

        db.command("ping")

        return {"status": "ok"}

    except Exception:

        raise HTTPException(503, "Database unavailable")





@app.post("/employees", status_code=201)

def create_employee(body: EmployeeIn):

    doc = body.model_dump()

    doc["email"] = str(body.email)

    doc["created_at"] = utc_now()

    try:

        db.employees.insert_one(doc)

    except DuplicateKeyError:

        raise HTTPException(409, "emp_code already exists")

    return public_employee(doc)





@app.get("/employees")

def list_employees(

    department: Optional[str] = None,

    page: int = Query(1, ge=1),

    page_size: int = Query(20, ge=1, le=100),

):

    q = {"department": department} if department is not None else {}

    total = db.employees.count_documents(q)

    docs = db.employees.find(q, {"_id": 0}).sort("emp_code", ASCENDING)

    docs = docs.skip(pagination(page, page_size)).limit(page_size)

    return {

        "items": [public_employee(x) for x in docs],

        "total": total, "page": page, "page_size": page_size,

    }





@app.post("/attendance/punch-in", status_code=201)

def punch_in(body: PunchInIn):

    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:

        raise HTTPException(404, "Employee not found")

    ts = parse_epoch_ms(body.punched_at)

    d = attendance_date(ts, emp["shift_start"], emp["shift_end"])

    if valid_date(d) < valid_date(emp["joined_on"]):

        raise HTTPException(422, "Attendance date precedes joining date")

    doc = {

        "emp_code": body.emp_code, "date": d, "status": body.status,

        "punch_in": ts, "punch_out": None, "work_hours": None,

        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),

        "overtime_minutes": 0, "half_day": False, "history": [],

    }

    try:

        db.attendance_logs.insert_one(doc)

    except DuplicateKeyError:

        raise HTTPException(409, "Attendance already exists for this date")

    return public_attendance(doc)





@app.post("/attendance/punch-out")

def punch_out(body: PunchOutIn):

    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:

        raise HTTPException(404, "Employee not found")

    ts = parse_epoch_ms(body.punched_at)

    # Search open shifts whose punch-in is no more than 24 hours earlier.

    candidate = db.attendance_logs.find_one({

        "emp_code": body.emp_code,

        "punch_in": {"$lte": ts, "$gte": ts - timedelta(hours=24)},

        "status": {"$in": list(PRESENT_STATUSES)},

        "punch_out": None,

    }, sort=[("punch_in", DESCENDING)])

    if not candidate:

        any_record = db.attendance_logs.find_one({

            "emp_code": body.emp_code, "punch_in": {"$lte": ts}

        })

        if any_record and any_record.get("punch_out") is not None:

            raise HTTPException(409, "Already punched out")

        raise HTTPException(404, "No open punch-in found")

    if ts <= candidate["punch_in"] or (ts - candidate["punch_in"]).total_seconds() > 86400:

        raise HTTPException(422, "Invalid punch-out time")

    derived = derive_fields({**candidate, "punch_out": ts}, emp)

    result = db.attendance_logs.update_one(

        {"_id": candidate["_id"], "punch_out": None},

        {"$set": derived},

    )

    if result.modified_count != 1:

        raise HTTPException(409, "Concurrent punch-out; retry")

    candidate.update(derived)

    return public_attendance(candidate)





@app.get("/attendance")

def list_attendance(

    emp_code: Optional[str] = None,

    date_from: Optional[str] = None,

    date_to: Optional[str] = None,

    status: Optional[str] = None,

    page: int = Query(1, ge=1),

    page_size: int = Query(20, ge=1, le=100),

):

    q = {}

    if emp_code:

        q["emp_code"] = emp_code

    if date_from:

        valid_date(date_from)

    if date_to:

        valid_date(date_to)

    if date_from and date_to and date_from > date_to:

        raise HTTPException(422, "date_from must not be after date_to")

    if date_from or date_to:

        q["date"] = {}

        if date_from:

            q["date"]["$gte"] = date_from

        if date_to:

            q["date"]["$lte"] = date_to

    if status:

        if status not in ALL_STATUSES:

            raise HTTPException(422, "Invalid status")

        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    docs = db.attendance_logs.find(q).sort(

        [("date", DESCENDING), ("emp_code", ASCENDING)]

    ).skip(pagination(page, page_size)).limit(page_size)

    return {

        "items": [public_attendance(x) for x in docs],

        "total": total, "page": page, "page_size": page_size,

    }





@app.patch("/attendance/{emp_code}/{date}")
def correct_attendance(emp_code: str, date: str, body: CorrectionIn):


    valid_date(date)

    emp = db.employees.find_one({"emp_code": emp_code})

    if not emp:

        raise HTTPException(404, "Employee not found")

    old = record_or_404(emp_code, date)

    new = dict(old)

    if body.status is not None:

        new["status"] = body.status

    for key in ("punch_in", "punch_out"):

        value = getattr(body, key)

        if value is not None:

            new[key] = parse_epoch_ms(value)

    if new["status"] in {"ABSENT", "LEAVE"}:

        if body.punch_in is not None or body.punch_out is not None:

            raise HTTPException(422, "ABSENT/LEAVE cannot have punch times")

        new["punch_in"] = new["punch_out"] = None

    derived = derive_fields(new, emp) if new["status"] in PRESENT_STATUSES else derive_fields(new, emp)

    new.update(derived)

    tracked = ["status", "punch_in", "punch_out", "work_hours",

               "late_minutes", "overtime_minutes", "half_day"]

    changes = {}

    for key in tracked:

        if old.get(key) != new.get(key):

            changes[key] = {"from": old.get(key), "to": new.get(key)}

    if not changes:

        raise HTTPException(422, "Correction does not change the record")

    entry = {

        "at": utc_now(), "by": body.regularized_by,

        "reason": body.reason, "changes": changes,

    }

    # Compare-and-swap prevents concurrent edits from overwriting history.

    expected_history = old.get("history", [])

    new_history = expected_history + [entry]

    result = db.attendance_logs.update_one(

        {"_id": old["_id"], "history": expected_history},

        {"$set": {**new, "history": new_history}},

    )

    if result.modified_count != 1:

        raise HTTPException(409, "Concurrent correction; retry")

    new["history"] = new_history

    return public_attendance(new)





@app.get("/analytics/employees/{emp_code}/monthly")

def employee_monthly(emp_code: str, month: str):

    start, end = month_bounds(month)

    emp = db.employees.find_one({"emp_code": emp_code})

    if not emp:

        raise HTTPException(404, "Employee not found")

    joined = max(valid_date(start), valid_date(emp["joined_on"]))

    working_days = sum(

        1 for i in range((valid_date(end) - joined).days + 1)

        if (joined + timedelta(days=i)).weekday() < 5

    ) if joined <= valid_date(end) else 0

    logs = list(db.attendance_logs.find({

        "emp_code": emp_code, "date": {"$gte": start, "$lte": end}

    }))

    present = sum(

        0.5 if x.get("half_day", False) else 1

        for x in logs if x["status"] in PRESENT_STATUSES

        and valid_date(x["date"]).weekday() < 5

    )

    leave = sum(x["status"] == "LEAVE" for x in logs)

    late = [x.get("late_minutes", 0) for x in logs]

    overtime = [x.get("overtime_minutes", 0) for x in logs]

    pct = rounded(present / working_days * 100, 4) if working_days else None

    return {

        "emp_code": emp_code, "month": month, "working_days": working_days,

        "present_days": rounded(present), "leave_days": leave,

        "late_count": sum(v > 0 for v in late),

        "total_late_minutes": sum(late), "total_overtime_minutes": sum(overtime),

        "attendance_pct": pct,

    }





@app.get("/analytics/departments/summary")

def department_summary(

    month: str, department: Optional[str] = None

):

    start, end = month_bounds(month)

    match = {"joined_on": {"$lte": end}}

    if department is not None:

        match["department"] = department

    employees = list(db.employees.find(match, {"_id": 0}))

    result = []

    for dep in sorted({e["department"] for e in employees}):

        codes = [e["emp_code"] for e in employees if e["department"] == dep]

        logs = list(db.attendance_logs.find({

            "emp_code": {"$in": codes}, "date": {"$gte": start, "$lte": end}

        }))

        work = [

            x["work_hours"] for x in logs

            if x["status"] in PRESENT_STATUSES and x.get("work_hours") is not None

        ]

        result.append({

            "department": dep, "headcount": len(codes),

            "present_days": rounded(sum(

                0.5 if x.get("half_day", False) else 1

                for x in logs if x["status"] in PRESENT_STATUSES

                and valid_date(x["date"]).weekday() < 5

            )),

            "avg_work_hours": rounded(sum(work) / len(work)) if work else None,

            "late_count": sum(x.get("late_minutes", 0) > 0 for x in logs),

            "total_late_minutes": sum(x.get("late_minutes", 0) for x in logs),

            "leave_count": sum(x["status"] == "LEAVE" for x in logs),

            "on_duty_count": sum(x["status"] == "ON_DUTY" for x in logs),

        })

    return {"month": month, "items": result}





@app.get("/analytics/leaderboard/late")

def late_leaderboard(

    month: str, limit: int = Query(10, ge=1, le=100),

    department: Optional[str] = None,

):

    start, end = month_bounds(month)

    pipeline = [

        {"$match": {"date": {"$gte": start, "$lte": end}}},

        {"$group": {"_id": "$emp_code",

                    "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},

                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}},

        {"$match": {"total_late_minutes": {"$gt": 0}}},

        {"$lookup": {"from": "employees", "localField": "_id",

                     "foreignField": "emp_code", "as": "employee"}},

        {"$unwind": "$employee"},

    ]

    if department is not None:

        pipeline.append({"$match": {"employee.department": department}})

    pipeline.extend([

        {"$setWindowFields": {

            "sortBy": {"total_late_minutes": -1},

            "output": {"rank": {"$rank": {}}},

        }},

        {"$match": {"rank": {"$lte": limit}}},

        {"$sort": {"total_late_minutes": -1, "_id": 1}},

        {"$project": {

            "_id": 0, "emp_code": "$_id", "name": "$employee.name",

            "department": "$employee.department", "rank": 1,

            "total_late_minutes": 1, "late_count": 1,

        }},

    ])

    return {"month": month, "items": list(db.attendance_logs.aggregate(pipeline))}





def build_department_trend_pipeline(department, start_dt, end_dt):

    return [

        {"$match": {"department": department}},

        {"$limit": 1},

        {

            "$project": {

                "_id": 0,

                "trend_date": {"$literal": start_dt},

            }

        },

        {

            "$densify": {

                "field": "trend_date",

                "range": {

                    "bounds": [start_dt, end_dt],

                    "step": 1,

                    "unit": "day",

                },

            }

        },

        {"$match": {"trend_date": {"$lt": end_dt}}},

        {

            "$lookup": {

                "from": "employees",

                "let": {

                    "day": {

                        "$dateToString": {

                            "format": "%Y-%m-%d",

                            "date": "$trend_date",

                            "timezone": "UTC",

                        }

                    }

                },

                "pipeline": [

                    {

                        "$match": {

                            "$expr": {

                                "$and": [

                                    {"$eq": ["$department", department]},

                                    {"$lte": ["$joined_on", "$$day"]},

                                ]

                            }

                        }

                    },

                    {"$project": {"_id": 0, "emp_code": 1}},

                ],

                "as": "employees",

            }

        },

        {

            "$lookup": {

                "from": "attendance_logs",

                "let": {

                    "day": {

                        "$dateToString": {

                            "format": "%Y-%m-%d",

                            "date": "$trend_date",

                            "timezone": "UTC",

                        }

                    },

                    "codes": "$employees.emp_code",

                },

                "pipeline": [

                    {

                        "$match": {

                            "$expr": {

                                "$and": [

                                    {"$eq": ["$date", "$$day"]},

                                    {"$in": ["$emp_code", "$$codes"]},

                                ]

                            }

                        }

                    },

                    {

                        "$project": {

                            "_id": 0,

                            "status": 1,

                            "half_day": 1,

                            "late_minutes": 1,

                        }

                    },

                ],

                "as": "logs",

            }

        },

        {

            "$set": {

                "headcount": {"$size": "$employees"},

                "is_working_day": {

                    "$and": [

                        {"$gte": [{"$dayOfWeek": "$trend_date"}, 2]},

                        {"$lte": [{"$dayOfWeek": "$trend_date"}, 6]},

                    ]

                },

                "present_count": {

                    "$sum": {

                        "$map": {

                            "input": {

                                "$filter": {

                                    "input": "$logs",

                                    "as": "log",

                                    "cond": {

                                        "$in": [

                                            "$$log.status",

                                            list(PRESENT_STATUSES),

                                        ]

                                    },

                                }

                            },

                            "as": "log",

                            "in": {

                                "$cond": [

                                    {

                                        "$eq": [

                                            {

                                                "$ifNull": [

                                                    "$$log.half_day",

                                                    False,

                                                ]

                                            },

                                            True,

                                        ]

                                    },

                                    0.5,

                                    1,

                                ]

                            },

                        }

                    }

                },

                "late_count": {

                    "$size": {

                        "$filter": {

                            "input": "$logs",

                            "as": "log",

                            "cond": {

                                "$gt": [

                                    {"$ifNull": ["$$log.late_minutes", 0]},

                                    0,

                                ]

                            },

                        }

                    }

                },

            }

        },

        {

            "$set": {

                "attendance_rate": {

                    "$cond": [

                        {

                            "$and": [

                                "$is_working_day",

                                {"$gt": ["$headcount", 0]},

                            ]

                        },

                        {

                            "$round": [

                                {

                                    "$divide": [

                                        "$present_count",

                                        "$headcount",

                                    ]

                                },

                                4,

                            ]

                        },

                        None,

                    ]

                }

            }

        },

        {

            "$setWindowFields": {

                "sortBy": {"trend_date": 1},

                "output": {

                    "moving_avg_7d": {

                        "$avg": "$attendance_rate",

                        "window": {"documents": [-6, 0]},

                    }

                },

            }

        },

        {

            "$project": {

                "_id": 0,

                "date": {

                    "$dateToString": {

                        "format": "%Y-%m-%d",

                        "date": "$trend_date",

                        "timezone": "UTC",

                    }

                },

                "is_working_day": 1,

                "headcount": 1,

                "present_count": {"$round": ["$present_count", 2]},

                "late_count": 1,

                "attendance_rate": 1,

                "moving_avg_7d": {

                    "$cond": [

                        {"$eq": ["$moving_avg_7d", None]},

                        None,

                        {"$round": ["$moving_avg_7d", 4]},

                    ]

                },

            }

        },

        {"$sort": {"date": 1}},

    ]





@app.get("/analytics/departments/{department}/trend")

def department_trend(

    department: str,

    from_date: str = Query(alias="from"),

    to_date: str = Query(alias="to"),

):

    start = valid_date(from_date)

    end = valid_date(to_date)



    if end < start or (end - start).days + 1 > 92:

        raise HTTPException(

            422,

            "Invalid date range; maximum 92 days",

        )



    if not db.employees.find_one({"department": department}):

        raise HTTPException(404, "Department not found")



    start_dt = datetime(

        start.year, start.month, start.day, tzinfo=UTC

    )



    end_exclusive = end + timedelta(days=1)

    end_dt = datetime(

        end_exclusive.year,

        end_exclusive.month,

        end_exclusive.day,

        tzinfo=UTC,

    )



    pipeline = build_department_trend_pipeline(

        department,

        start_dt,

        end_dt,

    )



    rows = list(db.employees.aggregate(pipeline))



    return {"department": department, "items": rows}

@app.get("/admin/explain/{endpoint}")
def explain(
    endpoint: str,
    month: Optional[str] = None,
    emp_code: Optional[str] = None,
    department: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: int = Query(10, ge=1, le=100),
):
    supported = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in supported:
        raise HTTPException(422, "Unsupported endpoint")

    if endpoint == "attendance_list":
        collection = db.attendance_logs
        query = {}

        if emp_code:
            query["emp_code"] = emp_code

        if date_from:
            valid_date(date_from)
        if date_to:
            valid_date(date_to)

        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must not be after date_to")

        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to

        if status:
            if status not in ALL_STATUSES:
                raise HTTPException(422, "Invalid status")
            query["status"] = status

        pipeline = [
            {"$match": query},
            {"$sort": {"date": -1, "emp_code": 1}},
            {"$skip": pagination(page, page_size)},
            {"$limit": page_size},
        ]

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month are required")

        start, end = month_bounds(month)
        collection = db.attendance_logs
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": start, "$lte": end},
                }
            }
        ]

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "month is required")

        _, end = month_bounds(month)
        collection = db.employees
        query = {"joined_on": {"$lte": end}}

        if department:
            query["department"] = department

        pipeline = [{"$match": query}]

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "month is required")

        start, end = month_bounds(month)
        collection = db.attendance_logs
        pipeline = [
            {"$match": {"date": {"$gte": start, "$lte": end}}},
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {
                        "$sum": {"$ifNull": ["$late_minutes", 0]}
                    },
                }
            },
            {"$match": {"total_late_minutes": {"$gt": 0}}},
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
        ]

        if department is not None:
            pipeline.append({"$match": {"employee.department": department}})

        pipeline.extend(
            [
                {
                    "$setWindowFields": {
                        "sortBy": {"total_late_minutes": -1},
                        "output": {"rank": {"$rank": {}}},
                    }
                },
                {"$match": {"rank": {"$lte": limit}}},
                {"$sort": {"total_late_minutes": -1, "_id": 1}},
                {
                    "$project": {
                        "_id": 0,
                        "emp_code": "$_id",
                        "name": "$employee.name",
                        "department": "$employee.department",
                        "rank": 1,
                        "total_late_minutes": 1,
                    }
                },
            ]
        )

    else:
        if not department or not from_date or not to_date:
            raise HTTPException(
                422,
                "department, from and to are required",
            )

        start = valid_date(from_date)
        end = valid_date(to_date)

        if end < start or (end - start).days + 1 > 92:
            raise HTTPException(
                422,
                "Invalid date range; maximum 92 days",
            )

        if not db.employees.find_one({"department": department}):
            raise HTTPException(404, "Department not found")

        start_dt = datetime(
            start.year,
            start.month,
            start.day,
            tzinfo=UTC,
        )
        end_exclusive = end + timedelta(days=1)
        end_dt = datetime(
            end_exclusive.year,
            end_exclusive.month,
            end_exclusive.day,
            tzinfo=UTC,
        )

        collection = db.employees
        pipeline = build_department_trend_pipeline(
            department,
            start_dt,
            end_dt,
        )

    explanation = collection.database.command(
        {
            "explain": {
                "aggregate": collection.name,
                "pipeline": pipeline,
                "cursor": {},
            },
            "verbosity": "executionStats",
        }
    )

    return {
        "endpoint": endpoint,
        "collection": collection.name,
        "explain": make_json_safe(explanation),
    }
