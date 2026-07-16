# Innova per Home Assistant

Custom component non ufficiale per l'app Innova 3.x di Solution Tech.

## Funzioni

- API REST e gRPC v2 dell'app Innova 3.x;
- riconoscimento automatico di climatizzatori, fancoil, termostati e pompe di calore;
- modalità Auto, Caldo, Freddo, Deumidificazione e Sola ventola secondo le capability;
- velocità Auto, Minima, Media, Massima e Boost secondo le capability;
- temperatura, setpoint e umidità in tempo reale;
- allarmi diagnostici con codice grezzo;
- flap, modalità silenziosa ed ERV quando supportati;
- stato del programma Manuale, Calendario o Antigelo;
- un solo stream realtime per abitazione, con polling di sicurezza configurabile.

I calendari settimanali restano gestiti dall'app Innova. Home Assistant espone lo
stato del programma attivo e i controlli HVAC immediati.

## Installazione e aggiornamenti con HACS

1. In HACS apri **Integrazioni**.
2. Aggiungi `https://github.com/davidedomotica/ha-innova` come repository personalizzato
   di tipo **Integrazione**.
3. Installa **Innova** e riavvia Home Assistant.
4. Aggiungi l'integrazione da **Impostazioni → Dispositivi e servizi**.

Le nuove release vengono proposte da HACS nella sezione aggiornamenti di Home
Assistant. Il repository controlla inoltre ogni giorno la pagina ufficiale Google
Play dell'app Innova: quando viene pubblicata una nuova versione, apre
automaticamente una segnalazione per la verifica delle nuove API e funzioni.

> Una nuova APK non può essere convertita automaticamente e in sicurezza in codice
> Home Assistant. L'aggiornamento HACS viene pubblicato solo dopo il controllo di
> compatibilità, così da non interrompere il funzionamento degli impianti.

## Installazione manuale

Copia `custom_components/innova` nella cartella `config/custom_components/` di Home
Assistant, riavvia Home Assistant e aggiungi l'integrazione **Innova**.

Il componente usa il cloud Innova e richiede una connessione Internet. È un progetto
di interoperabilità non affiliato a Innova o Solution Tech.
