# Short Commuter Survey (QR-friendly draft)

**Status: a question set only. This prototype has NO live response endpoint.** Nothing in the app, in this repository or behind any QR code collects, receives or stores responses. A QR code printed from this draft would lead nowhere unless a separate collection tool (for example a hosted form) is set up and its export is mapped to the `survey_responses` table. The 800 responses shown on the dashboard are **simulated** ("Simulated data for demonstration").

Design: 10 questions, about 2 minutes on a phone, one screen per question. Every answer maps to a field of the `survey_responses` table in `docs/DATA_SCHEMA.md`; the option codes below are the exact enum values the table and the dashboard use (the codes are stored, the labels are what the respondent sees). A test (`tests/test_survey_model.py`) checks that these codes equal the schema enums.

**Data minimisation.** No name, phone number, email, address, vehicle number, device identifier or precise location is asked or stored. Origin and destination are broad zones, not addresses. The optional free-text answer carries an instruction not to include personal details. `response_id` is a random identifier created on submission and `timestamp` is set by the system; neither identifies a person. Live responses would carry `source_type = live_demo_response` so they are never mixed up with the synthetic ones.

---

### Q1. How do you usually make this trip?
Field: `current_mode` (single choice, required)
- `car` - Car
- `two_wheeler` - Two-wheeler (scooter or motorcycle)
- `bus` - Bus
- `rail` - Train
- `shared_taxi` - Shared taxi or auto
- `other` - Something else

### Q2. What is the main purpose of this trip?
Field: `trip_purpose` (single choice, required)
- `work` - Work
- `education` - Education
- `shopping` - Shopping
- `health` - Health
- `leisure` - Leisure or visiting
- `other` - Other

### Q3. Where does this trip usually start?
Field: `origin_zone_id` (single choice from the zone list in the `zones` table, shown by zone name, for example Kotharia; required)

### Q4. Where does it usually end?
Field: `dest_zone_id` (single choice from the same zone list; required)

### Q5. Why do you use this mode? (choose all that apply)
Field: `reasons` (multiple choice, required). Show the first list to car, two-wheeler, shared-taxi and other respondents and the second list to bus and rail respondents.

Private-mode list:
- `flexibility` - I can leave whenever I want
- `door_to_door` - It takes me door to door
- `comfort` - It is more comfortable
- `bus_unreliable` - Buses are not reliable
- `no_ac_on_bus` - Buses have no AC
- `low_bus_frequency` - Buses are not frequent enough
- `crowding` - Buses are crowded
- `safety` - I feel safer
- `no_direct_route` - There is no direct bus
- `carries_goods_or_family` - I carry goods or family

Bus and rail list:
- `low_cost` - It costs less
- `no_private_vehicle` - I have no private vehicle
- `direct_route` - It is a direct route
- `avoid_parking_hassle` - I avoid parking hassle
- `safety` - I feel safer

### Q6. What would make you use the bus for this trip? (choose all that apply)
Field: `switch_conditions` (multiple choice, optional)
- `reliability` - Buses run on time
- `ac_comfort` - Air-conditioned, comfortable buses
- `frequency` - More frequent buses
- `lower_fare` - A lower fare
- `safety` - Safer travel
- `cleanliness` - Cleaner buses
- `real_time_info` - Live bus timings
- `parking_cost_or_hassle` - Higher parking cost or hassle
- `direct_route` - A direct route

### Q7. If those things were in place, would you switch to the bus for this trip?
Field: `switch_intent` (yes = 1, no = 0; asked only to car, two-wheeler, shared-taxi and other respondents; stored as null for bus and rail respondents)
- `1` - Yes
- `0` - No

### Q8. Anything else you would like to tell us? (optional, up to 280 characters)
Field: `open_text` (free text). Instruction shown under the box: "Please do not include your name, phone number or any personal details."

### Q9. Which income band is your household in? (optional)
Field: `income_band` (single choice, may be skipped)
- `low` - Low
- `lower_middle` - Lower-middle
- `middle` - Middle
- `upper_middle` - Upper-middle
- `high` - High

### Q10. Consent
Not stored as a field. A required tick-box before submission: "I understand my answers are anonymous and will be used only for transport planning analysis."

---

System-filled fields (not questions): `response_id`, `timestamp`, `source_type` (`live_demo_response` for real submissions).

Limitations of this draft: the questions are not cognitively tested or translated (a Gujarati and Hindi version would be needed), the income bands have no rupee thresholds, and the switch question is a stated intention, which usually overstates real behaviour.
