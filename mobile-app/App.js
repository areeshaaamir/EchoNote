import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  StatusBar,
  Vibration,
  Switch,
  Linking,
  Platform,
  AppState,
  Animated,
} from 'react-native';
import * as Notifications from 'expo-notifications';

const FIREBASE_DB_URL = 'https://echonote-170b6-default-rtdb.firebaseio.com';

// Configure foreground & background notification behavior
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

export default function App() {
  const [serverUrl, setServerUrl] = useState('https://echonote-api.echonoteapp.workers.dev');
  const [darkMode, setDarkMode] = useState(false);
  const [awayMode, setAwayMode] = useState(true);

  // Auth State
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Navigation & Synced Desktop Stream State
  const [activeTab, setActiveTab] = useState('dashboard');
  const [connected, setConnected] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [liveNotes, setLiveNotes] = useState([]);

  // Synced User Data (Keywords & Saved Notes)
  const [triggers, setTriggers] = useState([]);
  const [newTrigger, setNewTrigger] = useState('');
  const [savedNotes, setSavedNotes] = useState([]);

  // In-App Top Toast Banner State
  const [topBanner, setTopBanner] = useState(null);
  const bannerAnim = useRef(new Animated.Value(-140)).current;
  const bannerTimerRef = useRef(null);

  const appStateRef = useRef(AppState.currentState);
  const awayModeRef = useRef(awayMode);
  awayModeRef.current = awayMode;
  const lastAlertIdRef = useRef(null);

  // Editorial Palette matching EchoNote Desktop
  const theme = darkMode
    ? {
        headerBg: '#0D1512',
        bg: '#111614',
        card: '#19201D',
        subtle: '#222C28',
        border: '#2A3531',
        text: '#F3F4F2',
        muted: '#8F9995',
        accent: '#2E7D6B',
        pillBg: '#1D332D',
        pillText: '#7CC4B2',
        amberBg: '#3A2E1A',
        amberText: '#E5B567',
      }
    : {
        headerBg: '#14211D',
        bg: '#F6F4EF',
        card: '#FFFFFF',
        subtle: '#EDF2F0',
        border: '#E5E2DC',
        text: '#18201D',
        muted: '#6E7774',
        accent: '#1D4E43',
        pillBg: '#E6F0EC',
        pillText: '#1D4E43',
        amberBg: '#F7EEDB',
        amberText: '#9A6715',
      };

  const cleanHttpUrl = () => serverUrl.trim().replace(/\/+$/, '');

  const apiHeaders = {
    'Content-Type': 'application/json',
  };

  // --- REQUEST NOTIFICATION PERMISSIONS ON STARTUP ---
  useEffect(() => {
    (async () => {
      try {
        const { status: existingStatus } = await Notifications.getPermissionsAsync();
        if (existingStatus !== 'granted') {
          await Notifications.requestPermissionsAsync();
        }
      } catch (e) {}
    })();

    const sub = AppState.addEventListener('change', (nextState) => {
      appStateRef.current = nextState;
    });
    return () => sub.remove();
  }, []);

  // --- TOP SLIDE-DOWN IN-APP BANNER ---
  const showInAppBanner = (title, body) => {
    if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current);
    setTopBanner({ title, body });
    Animated.spring(bannerAnim, {
      toValue: Platform.OS === 'android' ? 34 : 12,
      useNativeDriver: true,
      bounciness: 6,
    }).start();

    bannerTimerRef.current = setTimeout(() => {
      hideInAppBanner();
    }, 6000);
  };

  const hideInAppBanner = () => {
    Animated.timing(bannerAnim, {
      toValue: -160,
      duration: 240,
      useNativeDriver: true,
    }).start(() => setTopBanner(null));
  };

  // --- FIRE SYSTEM NOTIFICATION WHEN USER IS IN WHATSAPP / BACKGROUND ---
  const triggerSystemNotification = async (title, body) => {
    try {
      await Notifications.scheduleNotificationAsync({
        content: {
          title,
          body,
          sound: true,
        },
        trigger: null,
      });
    } catch (e) {}
  };

  // --- AUTHENTICATION ---
  const handleAuth = async () => {
    setAuthError('');
    try {
      const endpoint = authMode === 'signup' ? '/api/signup' : '/api/login';
      const body =
        authMode === 'signup' ? { name, email, password } : { email, password };

      const res = await fetch(`${cleanHttpUrl()}${endpoint}`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setAuthError(data.detail || 'Authentication failed');
        return;
      }
      setUser(data);
      if (data.keywords) setTriggers(data.keywords);
    } catch (e) {
      setAuthError('Unable to reach EchoNote Cloud. Check your internet connection.');
    }
  };

  const startGoogleLogin = async () => {
    setAuthError('');
    const rawState = Date.now().toString() + Math.random().toString(36).slice(2);
    const loginUrl = `${cleanHttpUrl()}/auth/google/login?state=${encodeURIComponent(rawState)}`;
    await Linking.openURL(loginUrl);

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${cleanHttpUrl()}/auth/google/poll/${rawState}`, {
          headers: apiHeaders,
        });
        const data = await res.json();
        if (data.authenticated && data.user) {
          clearInterval(interval);
          setUser(data.user);
          if (data.user.keywords) setTriggers(data.user.keywords);
        }
      } catch (e) {}
    }, 2000);

    setTimeout(() => clearInterval(interval), 120000);
  };

  // --- SYNCED USER DATA FETCHERS ---
  const fetchTriggers = async (uid) => {
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/triggers/${uid}`, { headers: apiHeaders });
      const data = await res.json();
      if (data.keywords) setTriggers(data.keywords);
    } catch (e) {}
  };

  const addTrigger = async () => {
    const word = newTrigger.trim();
    if (!word || !user) return;
    const updated = Array.from(new Set([...triggers, word]));
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/triggers/${user.user_id}`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({ keywords: updated }),
      });
      const data = await res.json();
      if (data.keywords) setTriggers(data.keywords);
      setNewTrigger('');
    } catch (e) {}
  };

  const deleteTrigger = async (word) => {
    if (!user) return;
    const updated = triggers.filter((w) => w !== word);
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/triggers/${user.user_id}`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({ keywords: updated }),
      });
      const data = await res.json();
      if (data.keywords) setTriggers(data.keywords);
    } catch (e) {}
  };

  const fetchSavedNotes = async (uid) => {
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/notes/${uid}`, { headers: apiHeaders });
      const data = await res.json();
      if (data.notes) setSavedNotes(data.notes);
    } catch (e) {}
  };

  // --- REAL-TIME FIREBASE REST LISTENER (ZERO-DEPENDENCY) ---
  useEffect(() => {
    if (!user) {
      setConnected(false);
      return;
    }

    setLiveNotes([]);
    setAlerts([]);
    lastAlertIdRef.current = null;
    fetchTriggers(user.user_id);
    fetchSavedNotes(user.user_id);

    let isInitialLoad = true;
    let cancelled = false;

    const pollFirebase = async () => {
      if (cancelled) return;
      try {
        const [alertRes, notesRes] = await Promise.all([
          fetch(`${FIREBASE_DB_URL}/live_alerts/${user.user_id}.json`),
          fetch(`${FIREBASE_DB_URL}/notes/${user.user_id}.json`),
        ]);
        if (cancelled) return;
        setConnected(true);

        const data = await alertRes.json();
        if (data && data.id) {
          if (isInitialLoad) {
            isInitialLoad = false;
            lastAlertIdRef.current = data.id;
          } else if (data.id !== lastAlertIdRef.current) {
            lastAlertIdRef.current = data.id;
            const kwLabel = (data.keyword || 'ALERT').toUpperCase();
            const alertTitle = `EchoNote • ${kwLabel}`;
            const alertBody = data.transcript || `Keyword "${data.keyword}" detected.`;

            if (awayModeRef.current) {
              Vibration.vibrate([0, 600, 250, 600, 250, 800]);
              if (AppState.currentState !== 'active') {
                triggerSystemNotification(alertTitle, alertBody);
              } else {
                showInAppBanner(alertTitle, alertBody);
              }
            }

            setAlerts((prev) => [
              {
                id: data.id,
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                event_type: kwLabel,
                summary: `Detected "${data.keyword}" in lecture audio.`,
                original_text: data.transcript || '',
              },
              ...prev,
            ]);
          }
        } else {
          isInitialLoad = false;
        }

        const rawNotes = await notesRes.json();
        if (rawNotes) {
          const list = Object.values(rawNotes).sort(
            (a, b) => (b.created_at || 0) - (a.created_at || 0)
          );
          setSavedNotes(list);
          if (list[0]?.summary) {
            setLiveNotes(list[0].summary.split('\n').filter(Boolean));
          }
        }
      } catch (e) {
        if (!cancelled) setConnected(false);
      }
    };

    pollFirebase();
    const timer = setInterval(pollFirebase, 2000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [user]);

  // ==========================================================
  // LOGIN / SIGNUP SCREEN
  // ==========================================================
  if (!user) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.bg }]}>
        <StatusBar barStyle={darkMode ? 'light-content' : 'dark-content'} />
        <ScrollView contentContainerStyle={styles.authScroll}>
          <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
            <View style={styles.rowBetween}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <View style={styles.logoMark} />
                <Text style={[styles.brandTitle, { color: theme.text }]}>EchoNote</Text>
              </View>
              <TouchableOpacity
                style={[styles.pillBtn, { backgroundColor: theme.subtle }]}
                onPress={() => setDarkMode(!darkMode)}
              >
                <Text
                  numberOfLines={1}
                  style={[styles.pillBtnText, { color: theme.text }]}
                >
                  {darkMode ? 'Light' : 'Dark'}
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={[styles.mutedText, { color: theme.muted, marginTop: 6, marginBottom: 18 }]}>
              {authMode === 'login'
                ? 'Sign in with the same account used on Windows'
                : 'Create a student account'}
            </Text>

            <Text style={[styles.label, { color: theme.muted }]}>Cloud API Endpoint</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              value={serverUrl}
              onChangeText={setServerUrl}
              autoCapitalize="none"
            />

            {authMode === 'signup' && (
              <>
                <Text style={[styles.label, { color: theme.muted }]}>Full Name</Text>
                <TextInput
                  style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
                  placeholder="Areesha Aamir"
                  placeholderTextColor={theme.muted}
                  value={name}
                  onChangeText={setName}
                />
              </>
            )}

            <Text style={[styles.label, { color: theme.muted }]}>Email</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              placeholder="student@university.edu"
              placeholderTextColor={theme.muted}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
            />

            <Text style={[styles.label, { color: theme.muted }]}>Password</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              placeholder="••••••••"
              placeholderTextColor={theme.muted}
              secureTextEntry
              value={password}
              onChangeText={setPassword}
            />

            {authError ? <Text style={styles.errorText}>{authError}</Text> : null}

            <TouchableOpacity
              style={[styles.primaryBtn, { backgroundColor: theme.accent }]}
              onPress={handleAuth}
            >
              <Text numberOfLines={1} style={styles.primaryBtnText}>
                {authMode === 'login' ? 'Sign In' : 'Create Account'}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.primaryBtn,
                {
                  backgroundColor: theme.bg,
                  borderWidth: 1,
                  borderColor: theme.border,
                  marginTop: 10,
                },
              ]}
              onPress={startGoogleLogin}
            >
              <Text numberOfLines={1} style={[styles.primaryBtnText, { color: theme.text }]}>
                G   Continue with Google
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.switchBtn}
              onPress={() => {
                setAuthMode(authMode === 'login' ? 'signup' : 'login');
                setAuthError('');
              }}
            >
              <Text style={[styles.mutedText, { color: theme.muted }]}>
                {authMode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
              </Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ==========================================================
  // MAIN COMPANION WORKSPACE SHELL
  // ==========================================================
  const firstName = (user.name || 'Student').split(' ')[0];

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.headerBg }]}>
      <StatusBar barStyle="light-content" />

      {/* SLIDE-DOWN TOP IN-APP ALERT BANNER */}
      {topBanner && (
        <Animated.View
          style={[
            styles.topBanner,
            {
              backgroundColor: theme.headerBg,
              borderColor: '#79B8A8',
              transform: [{ translateY: bannerAnim }],
            },
          ]}
        >
          <View style={styles.rowBetween}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 }}>
              <View style={styles.logoMarkSmall} />
              <Text numberOfLines={1} style={styles.bannerTitle}>
                {topBanner.title}
              </Text>
            </View>
            <TouchableOpacity
              onPress={() => {
                Vibration.cancel();
                hideInAppBanner();
              }}
              style={styles.bannerCloseBtn}
            >
              <Text numberOfLines={1} style={styles.bannerCloseText}>
                Dismiss
              </Text>
            </TouchableOpacity>
          </View>
          <Text numberOfLines={3} style={styles.bannerBody}>
            {topBanner.body}
          </Text>
        </Animated.View>
      )}

      {/* Top Forest-Charcoal Brand Header */}
      <View style={[styles.navbar, { backgroundColor: theme.headerBg }]}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, flexShrink: 1 }}>
          <View style={styles.logoMark} />
          <View style={{ flexShrink: 1 }}>
            <Text numberOfLines={1} style={styles.navTitle}>
              EchoNote
            </Text>
            <Text numberOfLines={1} style={styles.navSub}>
              {firstName} • {connected ? 'Cloud Armed' : 'Connecting'}
            </Text>
          </View>
        </View>

        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <TouchableOpacity
            style={[styles.pillBtn, { backgroundColor: theme.accent }]}
            onPress={() => {
              fetchTriggers(user.user_id);
              fetchSavedNotes(user.user_id);
            }}
          >
            <Text numberOfLines={1} style={[styles.pillBtnText, { color: '#FFFFFF' }]}>
              Sync
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.pillBtn, { backgroundColor: '#253530' }]}
            onPress={() => setDarkMode(!darkMode)}
          >
            <Text numberOfLines={1} style={[styles.pillBtnText, { color: '#E2E8F0' }]}>
              {darkMode ? 'Light' : 'Dark'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.pillBtn, { borderWidth: 1, borderColor: '#253530' }]}
            onPress={() => setUser(null)}
          >
            <Text numberOfLines={1} style={[styles.pillBtnText, { color: '#A3B1AC' }]}>
              Exit
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Warm Alabaster Canvas */}
      <View style={{ flex: 1, backgroundColor: theme.bg }}>
        {/* Greeting + Alarm Switch Row */}
        <View style={styles.greetingRow}>
          <View style={{ flex: 1, paddingRight: 8 }}>
            <Text numberOfLines={1} style={[styles.mutedText, { color: theme.muted }]}>
              {new Date().toDateString()}
            </Text>
            <Text numberOfLines={1} style={[styles.greetingTitle, { color: theme.text }]}>
              Hello, {firstName}
            </Text>
          </View>
          <View style={[styles.awayPill, { backgroundColor: theme.card, borderColor: theme.border }]}>
            <Text numberOfLines={1} style={[styles.awayLabel, { color: theme.text }]}>
              Alarm
            </Text>
            <Switch
              value={awayMode}
              onValueChange={setAwayMode}
              trackColor={{ false: theme.subtle, true: theme.accent }}
              thumbColor="#FFFFFF"
            />
          </View>
        </View>

        {/* Navigation Tabs */}
        <View style={styles.tabBar}>
          {[
            { key: 'dashboard', label: 'Overview' },
            { key: 'alerts', label: `Alerts (${alerts.length})` },
            { key: 'keywords', label: 'Keywords' },
            { key: 'notes', label: 'Notes' },
          ].map((t) => (
            <TouchableOpacity
              key={t.key}
              style={[
                styles.tabItem,
                {
                  backgroundColor: activeTab === t.key ? theme.accent : theme.card,
                  borderColor: theme.border,
                },
              ]}
              onPress={() => {
                setActiveTab(t.key);
                if (t.key === 'keywords') fetchTriggers(user.user_id);
                if (t.key === 'notes') fetchSavedNotes(user.user_id);
              }}
            >
              <Text
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.85}
                style={[
                  styles.tabLabel,
                  { color: activeTab === t.key ? '#FFFFFF' : theme.text },
                ]}
              >
                {t.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <ScrollView style={styles.body}>
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'dashboard' && (
            <>
              {triggers.length > 0 && (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  style={{ marginBottom: 12 }}
                >
                  {triggers.slice(0, 8).map((w) => (
                    <View
                      key={w}
                      style={[styles.kwChip, { backgroundColor: theme.pillBg }]}
                    >
                      <Text numberOfLines={1} style={[styles.kwChipText, { color: theme.pillText }]}>
                        {w}
                      </Text>
                    </View>
                  ))}
                </ScrollView>
              )}

              {/* Desktop Companion Status & Latest Alert Card */}
              <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
                <View style={styles.rowBetween}>
                  <Text style={[styles.cardTitle, { color: theme.text }]}>Desktop Companion</Text>
                  <View style={[styles.kwChip, { backgroundColor: theme.pillBg, marginRight: 0 }]}>
                    <Text numberOfLines={1} style={[styles.kwChipText, { color: theme.pillText }]}>
                      {connected ? '● Armed' : '● Syncing'}
                    </Text>
                  </View>
                </View>
                <Text style={[styles.mutedText, { color: theme.muted, marginTop: 6, lineHeight: 18 }]}>
                  {awayMode
                    ? 'Alarm is ON. You will receive a top banner inside EchoNote and a system notification when using WhatsApp or other apps.'
                    : 'Alarm is muted. Keyword alerts will log silently below.'}
                </Text>

                {alerts.length > 0 && (
                  <View style={[styles.alertItem, { borderColor: theme.border }]}>
                    <View style={styles.rowBetween}>
                      <Text style={[styles.alertHead, { color: theme.amberText }]}>
                        Latest: {alerts[0].event_type.toLowerCase().replace('_', ' ')}
                      </Text>
                      <Text style={[styles.mutedText, { color: theme.muted }]}>{alerts[0].time}</Text>
                    </View>
                    <Text style={[styles.alertBody, { color: theme.text }]}>
                      {alerts[0].summary}
                    </Text>
                  </View>
                )}
              </View>

              {/* Latest Synced Lecture Summary Card */}
              <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
                <View style={styles.rowBetween}>
                  <Text style={[styles.cardTitle, { color: theme.text }]}>Latest AI Study Notes</Text>
                  <TouchableOpacity
                    style={[styles.pillBtn, { backgroundColor: theme.subtle }]}
                    onPress={() => {
                      setActiveTab('notes');
                      fetchSavedNotes(user.user_id);
                    }}
                  >
                    <Text numberOfLines={1} style={[styles.pillBtnText, { color: theme.text }]}>
                      Archive
                    </Text>
                  </TouchableOpacity>
                </View>

                {liveNotes.length === 0 ? (
                  <Text style={[styles.mutedText, { color: theme.muted, marginTop: 8, lineHeight: 18 }]}>
                    Notes saved from your Windows app appear here automatically via Firebase.
                  </Text>
                ) : (
                  liveNotes.slice(0, 6).map((n, i) => (
                    <Text key={i} style={[styles.noteLine, { color: theme.text }]}>
                      {n}
                    </Text>
                  ))
                )}
              </View>
            </>
          )}

          {/* TAB 2: ALERTS */}
          {activeTab === 'alerts' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <View style={styles.rowBetween}>
                <Text style={[styles.cardTitle, { color: theme.text }]}>Alerts</Text>
                <View style={[styles.kwChip, { backgroundColor: theme.amberBg, marginRight: 0 }]}>
                  <Text numberOfLines={1} style={[styles.kwChipText, { color: theme.amberText }]}>
                    {alerts.length} new
                  </Text>
                </View>
              </View>
              {alerts.length === 0 ? (
                <Text style={[styles.mutedText, { color: theme.muted, marginTop: 8 }]}>
                  No keyword alerts received yet.
                </Text>
              ) : (
                alerts.map((a) => (
                  <View key={a.id} style={[styles.alertItem, { borderColor: theme.border }]}>
                    <View style={styles.rowBetween}>
                      <Text style={[styles.alertHead, { color: theme.amberText }]}>
                        {a.event_type.toLowerCase().replace('_', ' ')}
                      </Text>
                      <Text style={[styles.mutedText, { color: theme.muted }]}>{a.time}</Text>
                    </View>
                    <Text style={[styles.alertBody, { color: theme.text }]}>{a.summary}</Text>
                    <Text style={[styles.mutedText, { color: theme.muted }]}>
                      "{a.original_text}"
                    </Text>
                  </View>
                ))
              )}
            </View>
          )}

          {/* TAB 3: KEYWORDS */}
          {activeTab === 'keywords' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <Text style={[styles.cardTitle, { color: theme.text }]}>Trigger Keywords</Text>
              <Text style={[styles.mutedText, { color: theme.muted, marginTop: 2, marginBottom: 12 }]}>
                Changes sync directly with your Windows app listener.
              </Text>

              <View style={{ flexDirection: 'row', gap: 8, marginBottom: 14 }}>
                <TextInput
                  style={[
                    styles.input,
                    {
                      flex: 1,
                      marginBottom: 0,
                      backgroundColor: theme.bg,
                      borderColor: theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="Add keyword..."
                  placeholderTextColor={theme.muted}
                  value={newTrigger}
                  onChangeText={setNewTrigger}
                />
                <TouchableOpacity
                  style={[styles.smallBtn, { backgroundColor: theme.accent }]}
                  onPress={addTrigger}
                >
                  <Text numberOfLines={1} style={styles.primaryBtnText}>
                    Add
                  </Text>
                </TouchableOpacity>
              </View>

              {triggers.map((w) => (
                <View
                  key={w}
                  style={[styles.triggerRow, { backgroundColor: theme.bg, borderColor: theme.border }]}
                >
                  <Text style={[styles.triggerWord, { color: theme.text }]}>{w}</Text>
                  <TouchableOpacity
                    style={{ paddingHorizontal: 8, paddingVertical: 4 }}
                    onPress={() => deleteTrigger(w)}
                  >
                    <Text numberOfLines={1} style={styles.removeText}>
                      Remove
                    </Text>
                  </TouchableOpacity>
                </View>
              ))}
            </View>
          )}

          {/* TAB 4: SAVED NOTES */}
          {activeTab === 'notes' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <Text style={[styles.cardTitle, { color: theme.text, marginBottom: 10 }]}>
                Saved Notes
              </Text>
              {savedNotes.length === 0 ? (
                <Text style={[styles.mutedText, { color: theme.muted }]}>No saved sessions yet.</Text>
              ) : (
                savedNotes.map((item) => {
                  const dateLabel =
                    typeof item.created_at === 'number'
                      ? new Date(item.created_at * 1000).toLocaleString()
                      : item.created_at || '';
                  return (
                    <View
                      key={item.id}
                      style={[styles.savedItem, { backgroundColor: theme.bg, borderColor: theme.border }]}
                    >
                      <Text style={[styles.savedTitle, { color: theme.text }]}>{item.title}</Text>
                      <Text
                        style={[
                          styles.mutedText,
                          { color: theme.muted, marginTop: 2, marginBottom: 6 },
                        ]}
                      >
                        {dateLabel}
                      </Text>
                      <Text style={[styles.noteLine, { color: theme.text }]}>
                        {item.summary || item.transcript || item.content}
                      </Text>
                    </View>
                  );
                })
              )}
            </View>
          )}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingTop: Platform.OS === 'android' ? 28 : 0 },
  authScroll: { flexGrow: 1, justifyContent: 'center', padding: 20 },
  logoMark: { width: 22, height: 22, borderRadius: 6, backgroundColor: '#79B8A8', flexShrink: 0 },
  logoMarkSmall: { width: 14, height: 14, borderRadius: 4, backgroundColor: '#79B8A8', flexShrink: 0 },
  topBanner: {
    position: 'absolute',
    top: 0,
    left: 14,
    right: 14,
    zIndex: 999,
    elevation: 12,
    borderWidth: 1.5,
    borderRadius: 14,
    padding: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.25,
    shadowRadius: 10,
  },
  bannerTitle: { color: '#79B8A8', fontSize: 13, fontWeight: '700', flexShrink: 1 },
  bannerBody: { color: '#F8FAFC', fontSize: 13, marginTop: 6, lineHeight: 18 },
  bannerCloseBtn: {
    backgroundColor: '#253530',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
    flexShrink: 0,
  },
  bannerCloseText: { color: '#E2E8F0', fontSize: 11, fontWeight: '600' },
  card: {
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    marginBottom: 14,
  },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brandTitle: { fontSize: 22, fontWeight: '700' },
  label: { fontSize: 12, fontWeight: '600', marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 13,
    marginBottom: 12,
  },
  primaryBtn: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  smallBtn: {
    paddingHorizontal: 18,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  primaryBtnText: { color: '#FFFFFF', fontWeight: '600', fontSize: 13, textAlign: 'center' },
  switchBtn: { alignItems: 'center', marginTop: 14 },
  errorText: { color: '#C2410C', fontSize: 12, marginBottom: 8 },
  navbar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 14,
    gap: 8,
  },
  navTitle: { fontSize: 17, fontWeight: '700', color: '#F8FAFC' },
  navSub: { fontSize: 11, color: '#A3B1AC' },
  pillBtn: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  pillBtnText: { fontSize: 12, fontWeight: '600', textAlign: 'center' },
  greetingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 8,
  },
  greetingTitle: {
    fontSize: 21,
    fontWeight: '700',
    fontFamily: Platform.OS === 'ios' ? 'Georgia' : 'serif',
  },
  awayPill: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 20,
    paddingLeft: 12,
    paddingRight: 6,
    paddingVertical: 2,
    gap: 6,
    flexShrink: 0,
  },
  awayLabel: { fontSize: 12, fontWeight: '600' },
  tabBar: { flexDirection: 'row', paddingHorizontal: 16, paddingTop: 6, gap: 6 },
  tabItem: {
    flex: 1,
    paddingVertical: 9,
    paddingHorizontal: 4,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabLabel: { fontSize: 12, fontWeight: '600', textAlign: 'center' },
  body: { flex: 1, padding: 16 },
  cardTitle: { fontSize: 15, fontWeight: '700' },
  mutedText: { fontSize: 12 },
  kwChip: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 12,
    marginRight: 6,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  kwChipText: { fontSize: 11, fontWeight: '600', textAlign: 'center' },
  alertItem: { borderTopWidth: 1, paddingTop: 10, marginTop: 10 },
  alertHead: { fontSize: 13, fontWeight: '700' },
  alertBody: { fontSize: 13, marginVertical: 3 },
  noteLine: { fontSize: 13, marginTop: 6, lineHeight: 19 },
  triggerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 8,
  },
  triggerWord: { fontSize: 13, fontWeight: '600' },
  removeText: { color: '#C2410C', fontSize: 12, fontWeight: '600' },
  savedItem: { borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 10 },
  savedTitle: { fontSize: 14, fontWeight: '700' },
});