from flask import Blueprint, request, jsonify
from app.services.data_provider import DataProvider
from app.services.ai_analyzer import AIAnalyzer
from app.models.analysis import AnalysisLog
from app import db, r
import json
from datetime import datetime, timedelta

api_bp = Blueprint('api', __name__)
ai_analyzer = AIAnalyzer()

@api_bp.route('/recommend', methods=['POST'])
def recommend():
    data = request.json
    model_name = data.get('model', 'gemini-2.5-flash')
    language = data.get('language', 'zh')
    
    # Construct cache key based on criteria
    criteria = {
        'capital': data.get('capital', 'Any'),
        'risk': data.get('risk', 'Any'),
        'frequency': data.get('frequency', 'Any')
    }
    
    # Cache key
    cache_key = f"rec:{criteria['capital']}:{criteria['risk']}:{criteria['frequency']}:{language}"
    
    try:
        # Check Redis (1 day expiration)
        cached = r.get(cache_key)
        if cached:
            print(f"Using cached recommendations for {cache_key}")
            return jsonify(json.loads(cached))
    except Exception as e:
        print(f"Redis Error: {e}")
        
    # Call AI
    result = ai_analyzer.recommend_stocks(criteria, model_name=model_name, language=language)
    
    # Cache if valid
    if result.get('recommendations'):
        try:
            r.setex(cache_key, 86400, json.dumps(result)) # 24 hours
        except Exception as e:
            print(f"Redis Set Error: {e}")
        
    return jsonify(result)

@api_bp.route('/portfolio_advice', methods=['POST'])
def portfolio_advice():
    data = request.json
    model_name = data.get('model', 'gemini-2.5-flash')
    language = data.get('language', 'zh')
    
    result = ai_analyzer.analyze_portfolio_item(data, model_name=model_name, language=language)
    return jsonify(result)

@api_bp.route('/translate', methods=['POST'])
def translate():
    data = request.json
    text = data.get('text')
    target_lang = data.get('target_lang', 'en')
    model_name = data.get('model', 'gemini-2.5-flash')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    result = ai_analyzer.translate_text(text, target_language=target_lang, model_name=model_name)
    return jsonify(result)

@api_bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    
    results = DataProvider.search_symbol(query)
    return jsonify(results)

@api_bp.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    symbol = data.get('symbol')
    model_name = data.get('model', 'gemini-2.5-flash') # Default to 2.5 Flash
    language = data.get('language', 'zh')
    
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
        
    # 1. Get K-line Data (Always fetch fresh market data)
    kline_data = DataProvider.get_kline_data(symbol)
    if not kline_data:
        return jsonify({'error': 'Could not fetch data for symbol'}), 404
        
    # 2. Check Cache (Database)
    # Look for analysis records for this symbol created within the last 24 hours
    # Note: Cache key theoretically should include model name, but for demo simplicity 
    # we might accept any recent valid analysis to save quota.
    # Let's stick to strict caching for now to be safe, or relax it. 
    # For "Agent" experience, a fresh analysis from a different model might be desired.
    # BUT, to save quota, let's reuse cache regardless of model if it's recent.
    
    one_day_ago = datetime.utcnow() - timedelta(hours=24)
    
    cached_log = AnalysisLog.query.filter(
        AnalysisLog.symbol == symbol,
        AnalysisLog.created_at >= one_day_ago
    ).order_by(AnalysisLog.created_at.desc()).first()
    
    # CACHE LOGIC ADJUSTMENT:
    # If language is requested, we should check if cached content is likely in that language?
    # Currently the prompt forces language. Detecting language of cache is hard without metadata.
    # For now, we'll assume cache is valid. If user wants translation, they use the translate button.
    # Alternatively, we could store language in metadata.
    # Given the requirement "If result exists, have component to translate", 
    # we can serve the cached result (likely ZH) and let frontend handle translation if needed.
    
    if cached_log and cached_log.analysis_result:
        try:
            analysis_result = json.loads(cached_log.analysis_result)
            # Validate cache structure: must contain 'trades' list and be from AI source
            if isinstance(analysis_result, dict) and 'trades' in analysis_result:
                # Check if it's a reliable source (not local strategy/mock)
                # Old records might not have 'source', so we can optionally check or assume ok if structure is complex.
                # For strict reliability as requested:
                if analysis_result.get('source') == 'ai_model':
                    print(f"Using cached analysis for {symbol} from {cached_log.created_at}")
                    return jsonify({
                        'symbol': symbol,
                        'kline_data': kline_data,
                        'analysis': analysis_result,
                        'source': 'cache'
                    })
                else:
                     print(f"Cached data for {symbol} is from {analysis_result.get('source')}. Ignoring.")
            else:
                print(f"Cached data for {symbol} has invalid/old structure. Re-analyzing.")
        except json.JSONDecodeError:
            # If cache is corrupted, ignore and re-analyze
            pass

    # 3. Run AI Analysis (if no cache)
    # Pass the selected model to the analyzer
    analysis_result = ai_analyzer.analyze(symbol, kline_data, model_name=model_name, language=language)
    
    # 4. Save to DB (Only cache high-quality AI analysis, skip local/mock data)
    if analysis_result.get('source') == 'ai_model':
        try:
            log = AnalysisLog(
                symbol=symbol,
                analysis_result=json.dumps(analysis_result)
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            print(f"DB Error: {e}")
            db.session.rollback()
    else:
        print(f"Skipping cache for {symbol} (Source: {analysis_result.get('source')})")
        
    return jsonify({
        'symbol': symbol,
        'kline_data': kline_data,
        'analysis': analysis_result,
        'source': 'ai'
    })
