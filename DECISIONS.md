# DECISIONS.md

1. **Indexes.** I created a unique index on `employees.emp_code` to prevent duplicate employees, and a unique compound index on `attendance_logs.emp_code` and `date` to prevent duplicate daily attendance. I also added indexes for attendance date and employee queries, and for department and joining-date queries. These support the main filters and lookups. I would avoid adding indexes without a measured query need because indexes consume storage and slow writes.

2. **Punch-in race.** Both requests may initially reach the database together. The unique compound attendance index allows only one record for the same employee and date. One request succeeds with 201; the other receives a duplicate-key error, which the API converts to 409. This avoids relying on a check followed by an insert.

3. **Ties.** The leaderboard uses competition ranking. Employees tied at the cutoff share the same rank, and all employees with rank less than or equal to `limit` are returned. Therefore, the response can contain more rows than the limit. Rows are ordered by late minutes descending, then employee code ascending.

4. **Headcount.** The department summary starts from employees and joins attendance logs. Employees without matching logs remain included, so headcount is not based only on attendance records.

5. **100x data.** I would test with production-sized data, inspect execution statistics, and tune indexes and aggregation pipelines using measured bottlenecks.