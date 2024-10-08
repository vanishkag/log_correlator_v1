from flask import Flask, jsonify, request
from pymongo import MongoClient
from flask_cors import CORS
from datetime import datetime, timedelta
import subprocess
import threading
import time
from bson import ObjectId

app = Flask(__name__)
CORS(app)

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['event_logs']
collection = db['logs']
alerts_collection = db['alerts']

# Correlation Groups
correlation_groups = {
    "System Events": [6008, 1, 20, 44, 134, 30, 2, 13, 37, 41, 43, 50, 51, 62, 63, 64, 70, 71, 74, 75, 7001, 1501, 5, 19],
    "Application Events": [1001, 1000, 258, 172, 10001, 10016, 32, 105, 1026, 1029, 1041, 1015, 1014, 1050, 11708, 11709, 11710, 1073742091, 10010, 10000],
    "Security Events": [4624, 4625, 4633, 4670, 4720, 4732, 4740, 4776, 4800, 4648, 4738, 4798, 4799, 5379, 4649, 4672, 4673, 4688, 4690, 4689, 4634],
    "Network Events": [5059, 4946, 5058, 5382, 5156, 5158, 5159, 5460, 5461, 5462],
    "Hardware Events": [15, 43, 16, 18, 28, 12, 31, 32, 34, 35],
    "Informational Events": [1073748869, 1073748864, 1074069522, 1073742858, 1073758208, 10100, 10101, 10102, 10200, 1073750851, 1073741829],
    "Error Events": [-1073725430, 0, 1108, 1021, 1022, 1023, 1024, 1040, 1050, -2147477648, -2147482948],
    "Service and System Changes": [7045, 4864, 4680, 4681, 4692, 4693, 4694, 4695],
    "Active Directory Events": [8224, 566, 4724, 4726, 4728, 4730, 4732, 4733, 4756, 4767],
    "Cryptographic and Security Operations": [5061, 506, 507, 5071, 5072, 5080, 5090, 5091, 5100, 5110]
}

def adjust_timestamp(timestamp):
    if not isinstance(timestamp, datetime):
        raise ValueError("Timestamp must be a datetime object")
    adjusted_time = timestamp - timedelta(hours=5, minutes=30)
    return adjusted_time.strftime('%m/%d/%Y, %I:%M:%S %p')

def get_event_name(event_id):
    for category, ids in correlation_groups.items():
        if event_id in ids:
            return category
    return "Unknown Event ID"

@app.route('/logs', methods=['GET'])
def get_logs():
    query = {}
    if 'search' in request.args:
        search = request.args.get('search')
        query = {'message': {'$regex': search, '$options': 'i'}}

    logs = list(collection.find(query).sort('timeGenerated', -1))
    for log in logs:
        log['_id'] = str(log['_id'])
        event_id = log.get('eventID')
        log['eventName'] = get_event_name(event_id)
        log['timestamp'] = log.get('timeGenerated') if log.get('timeGenerated') else 'No timestamp available'
        log['level'] = log.get('level', 'Unknown')
        log['source'] = log.get('source', 'Unknown')
        log['message'] = log.get('message', 'No message available').split('\n')[0]
    return jsonify(logs)

@app.route('/logs/total', methods=['GET'])
def get_log_count():
    count = collection.count_documents({})
    return jsonify({'total': count})

@app.route('/logs/chart', methods=['GET'])
def get_logs_chart():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify([]), 400

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_date = datetime(date.year, date.month, date.day, 0, 0, 0)
        end_date = start_date + timedelta(days=1)

        pipeline = [
            {"$match": {"timeGenerated": {"$gte": start_date, "$lt": end_date}}},
            {"$group": {"_id": {"hour": {"$hour": "$timeGenerated"}}, "count": {"$sum": 1}}},
            {"$sort": {"_id.hour": 1}}
        ]

        results = list(collection.aggregate(pipeline))

        chart_data = []
        for result in results:
            hour_str = f"{result['_id']['hour']:02d}:00"
            chart_data.append({"hour": hour_str, "count": result["count"]})

        return jsonify(chart_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/logs/piechart', methods=['GET'])
def get_piechart_data():
    date = request.args.get('date')
    if not date:
        return jsonify({"error": "Date is required"}), 400

    try:
        start_date = datetime.strptime(date, '%Y-%m-%d')
        end_date = start_date.replace(hour=23, minute=59, second=59)

        pipeline = [
            {"$match": {"timeGenerated": {"$gte": start_date, "$lte": end_date}}},
            {"$group": {"_id": "$eventTypeName", "count": {"$sum": 1}}}
        ]
        results = list(collection.aggregate(pipeline))

        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/alerts', methods=['POST'])
def create_alert():
    alert_data = request.json
    if not alert_data or 'eventID' not in alert_data:
        return jsonify({"error": "eventID is required"}), 400

    alert_data.pop('email', None)
    alert_data['logDetails'] = []
    alert_data['totalLogs'] = 0
    alerts_collection.insert_one(alert_data)
    return jsonify({"message": "Alert created successfully"}), 201

@app.route('/alerts', methods=['GET'])
def get_alerts():
    alerts = list(alerts_collection.find())
    for alert in alerts:
        alert['_id'] = str(alert['_id'])
        event_id = int(alert.get('eventID'))
        alert['eventName'] = get_event_name(event_id) if event_id else 'N/A'

        # Fetch the total count of logs for the specific eventID
        total_logs = collection.count_documents({"eventID": event_id})
        alert['totalLogs'] = total_logs

        # Fetch latest 5 log details for the specific eventID associated with the alert
        log_details = list(collection.find({"eventID": event_id}).sort('timeGenerated', -1).limit(5))
        
        for log in log_details:
            log['_id'] = str(log['_id'])
            log['timestamp'] = log.get('timeGenerated') if log.get('timeGenerated') else 'No timestamp available'
            log['level'] = log.get('level', 'Unknown')
            log['source'] = log.get('source', 'Unknown')
            log['message'] = log.get('message', 'No message available').split('\n')[0]
        
        alert['logDetails'] = log_details

    return jsonify(alerts)

@app.route('/logs/event', methods=['GET'])
def get_logs_by_event_id():
    event_id = request.args.get('eventID')
    if not event_id:
        return jsonify({"error": "eventID is required"}), 400
    
    try:
        event_id = int(event_id)
        logs = list(collection.find({"eventID": event_id}).sort('timeGenerated', -1))
        
        for log in logs:
            log['_id'] = str(log['_id'])
            log['eventName'] = get_event_name(event_id)
            log['timestamp'] = log.get('timeGenerated') if log.get('timeGenerated') else 'No timestamp available'
            log['level'] = log.get('level', 'Unknown')
            log['source'] = log.get('source', 'Unknown')
            log['message'] = log.get('message', 'No message available').split('\n')[0]
        
        return jsonify(logs)
    except ValueError:
        return jsonify({"error": "Invalid eventID format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/alerts/<id>', methods=['DELETE'])
def delete_alert(id):
    try:
        from bson import ObjectId
        result = alerts_collection.delete_one({"_id": ObjectId(id)})
        if result.deleted_count == 1:
            return jsonify({"message": "Alert deleted successfully"}), 200
        else:
            return jsonify({"error": "Alert not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
